"""Owner-composed simulation authority. No network/payment SDK or real-money path.

SQLite serializes policy/reservation/provider/settlement changes. The keyed audit
chain authenticates both events and authoritative state. It must run outside an
agent's writable filesystem; host administrators remain a trusted boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .agent_registry import load_agent_registry, REGISTRY_PATH
from .action_records import safe


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


class IntegrityError(RuntimeError):
    pass


CATALOG = {
    'simulation.lookup': {'merchant': 'simulation.local', 'amount': 100, 'currency': 'USD'},
    'simulation.analysis': {'merchant': 'simulation.local', 'amount': 300, 'currency': 'USD'},
    'simulation.large': {'merchant': 'simulation.local', 'amount': 600, 'currency': 'USD'},
}
EXTERNAL_PROVIDERS = {name: 'UNAVAILABLE_UNIMPLEMENTED' for name in
                      ('cloudflare-wallets', 'x402', 'mpp', 'api-billing', 'regulated')}
DEFAULT_POLICY = dict(max_purchase=500, daily=1000, monthly=5000, approval_above=200,
                      rate_per_minute=5, merchants=['simulation.local'],
                      services=['simulation.lookup', 'simulation.analysis', 'simulation.large'],
                      currencies=['USD'])
HOLD = ('RESERVED', 'INDETERMINATE')
CHARGED = ('SETTLED', 'REFUNDED')


class UnavailablePaymentAdapter:
    """Future adapter contract, deliberately incapable of network execution."""
    def __init__(self, name):
        if name not in EXTERNAL_PROVIDERS: raise ValueError('Unknown provider')
        self.name=name

    def execute(self, *args, **kwargs):
        raise PermissionError('External payment providers are unavailable and disabled')

    status=execute
    refund=execute


class SimulatedPaymentAdapter:
    """Local transactional adapter: missing receipt proves no simulated execution."""
    name='simulated'

    def execute(self, db, txid, result, scenario):
        if scenario in {'success','ambiguous_after'}:
            db.execute('INSERT INTO provider VALUES(?,?,?)',(txid,'ACCEPTED',canonical(result)))
        elif scenario in {'outage','partial'}:
            db.execute('INSERT INTO provider VALUES(?,?,?)',(txid,'FAILED',canonical(dict(error=scenario))))
        return 'SETTLED' if scenario=='success' else 'FAILED' if scenario in {'outage','partial'} else 'INDETERMINATE'

    def status(self, db, txid):
        return db.execute('SELECT * FROM provider WHERE id=?',(txid,)).fetchone()

    def refund(self, db, txid):
        db.execute("UPDATE provider SET state='REFUNDED' WHERE id=?",(txid,))


class FinancialSimulation:
    def __init__(self, path, key, *, initial_balance=10000, global_ceiling=10000,
                 policy=None, clock=time.time):
        if type(key) is not bytes or len(key) < 32:
            raise ValueError('An authority-only simulation audit key is required')
        for n in (initial_balance, global_ceiling):
            if type(n) is not int or not 0 <= n <= 10**9:
                raise ValueError('Invalid simulated funding')
        self.path, self.key, self.clock = str(path), key, clock
        # No injectable adapter selector can activate an external provider.
        self.provider=SimulatedPaymentAdapter()
        self.policy = json.loads(canonical(policy or DEFAULT_POLICY))
        for field in ('max_purchase', 'daily', 'monthly', 'approval_above', 'rate_per_minute'):
            if type(self.policy.get(field)) is not int or self.policy[field] < 0:
                raise ValueError('Invalid authority policy')
        for field in ('merchants', 'services', 'currencies'):
            if type(self.policy.get(field)) is not list:
                raise ValueError('Invalid authority scope')
        agents = load_agent_registry()['agents']
        self.identities = {a['immutable_id']: a['name'] for a in agents}
        self.registry_sha = hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest()
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect(check=False) as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS treasury (id INTEGER PRIMARY KEY CHECK(id=1),
                funding INTEGER NOT NULL CHECK(funding>=0), ceiling INTEGER NOT NULL CHECK(ceiling>=0),
                frozen INTEGER NOT NULL, registry_sha TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS wallets (agent TEXT PRIMARY KEY, wallet TEXT UNIQUE NOT NULL,
                policy TEXT NOT NULL, state TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS transactions (id TEXT PRIMARY KEY, agent TEXT NOT NULL,
                request_key TEXT UNIQUE NOT NULL, nonce TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
                digest TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0), currency TEXT NOT NULL,
                budget_at REAL NOT NULL, expires REAL NOT NULL, state TEXT NOT NULL,
                approval TEXT, result TEXT, reason TEXT NOT NULL DEFAULT '');
              CREATE TABLE IF NOT EXISTS provider (id TEXT PRIMARY KEY, state TEXT NOT NULL, result TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY, epoch REAL NOT NULL,
                agent TEXT, event TEXT NOT NULL, previous TEXT NOT NULL, body TEXT NOT NULL, mac TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
                BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
              CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
                BEGIN SELECT RAISE(ABORT,'audit immutable'); END;
            ''')
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM treasury').fetchone():
                db.execute('INSERT INTO treasury VALUES(1,?,?,0,?)',
                           (initial_balance, global_ceiling, self.registry_sha))
                for agent in sorted(self.identities):
                    db.execute('INSERT INTO wallets VALUES(?,?,?,?)',
                               (agent, 'sim-wallet:'+agent, canonical(self.policy), 'ACTIVE'))
                self._audit(db, 'INITIALIZED', None, dict(mode='SIMULATED', agents=sorted(self.identities)))
            self._verify(db)
            if db.execute('SELECT registry_sha FROM treasury').fetchone()[0] != self.registry_sha:
                raise IntegrityError('Registry changed; owner reconciliation required')
            if {row[0] for row in db.execute('SELECT agent FROM wallets')} != set(self.identities):
                raise IntegrityError('Wallet identity mismatch')

    @contextmanager
    def connect(self, check=True):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            if check:
                db.execute('BEGIN IMMEDIATE')
                self._verify(db)
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _state(self, db):
        return {table: [dict(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY 1')]
                for table in ('treasury', 'wallets', 'transactions', 'provider')}

    def _state_sha(self, db):
        return hashlib.sha256(canonical(self._state(db)).encode()).hexdigest()

    def _audit(self, db, event, agent, details):
        previous = db.execute('SELECT seq,mac FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        seq, prev = (previous[0]+1, previous[1]) if previous else (1, '0'*64)
        now = self.clock()
        body = canonical(dict(seq=seq, timestamp=now, agent=agent, event=event,
                              details=safe(details), state_sha=self._state_sha(db)))
        mac = hmac.new(self.key, (prev+body).encode(), hashlib.sha256).hexdigest()
        db.execute('INSERT INTO audit VALUES(?,?,?,?,?,?,?)', (seq, now, agent, event, prev, body, mac))

    def _verify(self, db):
        previous, last, sequence = '0'*64, None, 0
        for row in db.execute('SELECT * FROM audit ORDER BY seq'):
            sequence += 1
            try:
                body = json.loads(row['body'])
                required=('seq','timestamp','agent','event','state_sha')
                if type(body) is not dict or any(field not in body for field in required):
                    raise ValueError('Malformed audit event')
            except (ValueError,TypeError) as exc:
                raise IntegrityError('Financial audit shape failure') from exc
            expected = hmac.new(self.key, (previous+row['body']).encode(), hashlib.sha256).hexdigest()
            if (row['seq'] != sequence or row['previous'] != previous
                    or body['seq'] != row['seq'] or body['timestamp'] != row['epoch']
                    or body['agent'] != row['agent'] or body['event'] != row['event']
                    or not hmac.compare_digest(row['mac'], expected)):
                raise IntegrityError('Financial audit integrity failure')
            previous, last = row['mac'], body
        if last is None or last['state_sha'] != self._state_sha(db):
            raise IntegrityError('Financial state differs from authenticated audit')
        self._invariants(db)

    def _balances(self, db):
        treasury = dict(db.execute('SELECT * FROM treasury').fetchone())
        reserved = db.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE state IN ('RESERVED','INDETERMINATE')").fetchone()[0]
        settled = db.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE state='SETTLED'").fetchone()[0]
        gross = db.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE state IN ('SETTLED','REFUNDED')").fetchone()[0]
        return dict(funding=treasury['funding'], reserved=reserved, settled=settled, gross=gross,
                    available=treasury['funding']-settled-reserved, ceiling=treasury['ceiling'],
                    frozen=bool(treasury['frozen']), mode='SIMULATED', real_money=False)

    def _invariants(self, db):
        balance = self._balances(db)
        if balance['available'] < 0 or balance['gross']+balance['reserved'] > balance['ceiling']:
            raise IntegrityError('Treasury invariant violated')
        for tx in db.execute("SELECT * FROM transactions WHERE state IN ('SETTLED','REFUNDED')"):
            receipt = db.execute('SELECT * FROM provider WHERE id=?', (tx['id'],)).fetchone()
            if not receipt or receipt['state'] != ('REFUNDED' if tx['state']=='REFUNDED' else 'ACCEPTED'):
                raise IntegrityError('Settlement lacks a matching simulated provider receipt')

    def quote(self, agent, service, *, ttl=60):
        if agent not in self.identities or service not in CATALOG or type(ttl) is not int or not 1 <= ttl <= 300:
            with self.connect() as db:
                self._audit(db, 'QUOTE_DENIED', agent, dict(service=str(service)[:100]))
            raise ValueError('Unknown identity/service or invalid quote TTL')
        value = dict(agent=agent, service=service, **CATALOG[service], nonce=uuid.uuid4().hex,
                     issued=self.clock(), expires=self.clock()+ttl, provider='simulated')
        value['signature'] = hmac.new(self.key, canonical(value).encode(), hashlib.sha256).hexdigest()
        with self.connect() as db:
            self._audit(db, 'QUOTED', agent, value)
        return value

    def discover(self, agent):
        with self.connect() as db:
            wallet = db.execute('SELECT * FROM wallets WHERE agent=?', (agent,)).fetchone()
            if not wallet:
                self._audit(db, 'DISCOVERY_DENIED', agent, {})
                return []
            policy = json.loads(wallet['policy'])
            services = [dict(service=k, **v, provider='simulated', mode='SIMULATED') for k,v in CATALOG.items()
                        if k in policy['services'] and v['merchant'] in policy['merchants'] and v['currency'] in policy['currencies']]
            self._audit(db, 'DISCOVERED', agent, dict(services=services))
            return services

    def _policy_reason(self, db, agent, quote, *, reserve=False):
        wallet = db.execute('SELECT * FROM wallets WHERE agent=?', (agent,)).fetchone()
        if not wallet: return 'UNKNOWN_IDENTITY'
        if wallet['state'] != 'ACTIVE': return 'AGENT_'+wallet['state']
        if db.execute('SELECT frozen FROM treasury').fetchone()[0]: return 'TREASURY_FROZEN'
        policy = json.loads(wallet['policy'])
        if quote['provider'] != 'simulated': return 'EXTERNAL_PROVIDER_DISABLED'
        if quote['merchant'] not in policy['merchants']: return 'MERCHANT_DENIED'
        if quote['service'] not in policy['services']: return 'SERVICE_DENIED'
        if quote['currency'] not in policy['currencies']: return 'CURRENCY_DENIED'
        if quote['amount'] > policy['max_purchase']: return 'PER_PURCHASE_LIMIT'
        if self.clock() >= quote['expires']: return 'EXPIRED'
        if reserve:
            now = time.gmtime(self.clock())
            day = time.strftime('%Y-%m-%d', now)
            month = time.strftime('%Y-%m', now)
            rows = list(db.execute("SELECT amount,budget_at,state FROM transactions WHERE agent=? AND state IN ('RESERVED','INDETERMINATE','SETTLED','REFUNDED')", (agent,)))
            daily = sum(r['amount'] for r in rows if r['state'] in HOLD or time.strftime('%Y-%m-%d',time.gmtime(r['budget_at']))==day)
            monthly = sum(r['amount'] for r in rows if r['state'] in HOLD or time.strftime('%Y-%m',time.gmtime(r['budget_at']))==month)
            if daily+quote['amount'] > policy['daily']: return 'DAILY_LIMIT'
            if monthly+quote['amount'] > policy['monthly']: return 'MONTHLY_LIMIT'
            balance = self._balances(db)
            if balance['gross']+balance['reserved']+quote['amount'] > balance['ceiling']: return 'SHARED_CEILING'
            if quote['amount'] > balance['available']: return 'INSUFFICIENT_TREASURY'
        return None

    def request(self, agent, request, task_id):
        # Caller identity is supplied only by the trusted dispatcher, never prompts.
        with self.connect() as db:
            def deny(reason):
                self._audit(db, 'REQUEST_DENIED', agent, dict(reason=reason, task_id=task_id,
                            request=request if isinstance(request,dict) else {'invalid':True}))
                return dict(state='DENIED', reason=reason, mode='SIMULATED')
            if type(request) is not dict or set(request) != {'quote','idempotency_key','objective'}:
                return deny('REQUEST_FIELDS_INVALID')
            quote = request['quote']
            if (type(quote) is not dict or set(quote) != {'agent','service','merchant','amount','currency','nonce','issued','expires','provider','signature'}
                    or type(quote['amount']) is not int or not 1 <= quote['amount'] <= 10**9
                    or type(quote['issued']) not in (int,float) or type(quote['expires']) not in (int,float)
                    or not math.isfinite(quote['issued']) or not math.isfinite(quote['expires'])
                    or type(request['idempotency_key']) is not str or not 1 <= len(request['idempotency_key']) <= 128
                    or type(request['objective']) is not str or not 1 <= len(request['objective']) <= 1000):
                return deny('REQUEST_FIELDS_INVALID')
            unsigned = {k:v for k,v in quote.items() if k!='signature'}
            expected = hmac.new(self.key, canonical(unsigned).encode(), hashlib.sha256).hexdigest()
            if type(quote['signature']) is not str or not hmac.compare_digest(expected,quote['signature']):
                return deny('QUOTE_INVALID')
            if quote['agent'] != agent: return deny('IDENTITY_MISMATCH')
            if quote['issued'] > self.clock() or not 0 < quote['expires']-quote['issued'] <= 300:
                return deny('INVALID_AUTHORIZATION_TIME')
            digest = hashlib.sha256(canonical(dict(agent=agent, request=request)).encode()).hexdigest()
            prior = db.execute('SELECT * FROM transactions WHERE request_key=?',(request['idempotency_key'],)).fetchone()
            if prior:
                if prior['digest'] != digest: return deny('IDEMPOTENCY_CONFLICT')
                self._audit(db,'DUPLICATE',agent,dict(id=prior['id'],task_id=task_id))
                return self._receipt(prior)
            if db.execute('SELECT 1 FROM transactions WHERE nonce=?',(quote['nonce'],)).fetchone(): return deny('QUOTE_REPLAY')
            policy = json.loads(db.execute('SELECT policy FROM wallets WHERE agent=?',(agent,)).fetchone()[0]) if agent in self.identities else {}
            rate = db.execute("SELECT COUNT(*) FROM audit WHERE agent=? AND event IN ('REQUESTED','REQUEST_DENIED') AND epoch>?",(agent,self.clock()-60)).fetchone()[0]
            if rate >= policy.get('rate_per_minute',0): return deny('RATE_LIMIT')
            reason = self._policy_reason(db,agent,quote)
            if reason: return deny(reason)
            txid = uuid.uuid4().hex
            state = 'WAITING_APPROVAL' if quote['amount'] > policy['approval_above'] else 'AUTHORIZED'
            db.execute('INSERT INTO transactions(id,agent,request_key,nonce,request,digest,amount,currency,budget_at,expires,state) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (txid,agent,request['idempotency_key'],quote['nonce'],canonical(dict(request,task_id=task_id)),digest,
                        quote['amount'],quote['currency'],self.clock(),quote['expires'],state))
            self._audit(db,'REQUESTED',agent,dict(id=txid,task_id=task_id,policy_decision=state,request=request))
            return self._receipt(db.execute('SELECT * FROM transactions WHERE id=?',(txid,)).fetchone())

    def _receipt(self, row):
        return {k:row[k] for k in ('id','agent','state','amount','currency','approval','reason')} | dict(
            mode='SIMULATED', real_money=False, result=json.loads(row['result']) if row['result'] else None)

    def _tx(self, db, txid, agent=None):
        row = db.execute('SELECT * FROM transactions WHERE id=?',(txid,)).fetchone()
        if not row or (agent is not None and row['agent'] != agent):
            self._audit(db,'IDENTITY_DENIED',agent,dict(id=str(txid)))
            return None
        return row

    def owner_control(self, operation, *, agent=None, txid=None, value=None):
        # Trusted authority composition calls this only after existing owner auth.
        with self.connect() as db:
            if operation=='freeze' and type(value) is bool:
                db.execute('UPDATE treasury SET frozen=?',(int(value),))
            elif operation in ('suspend','revoke','resume') and agent in self.identities:
                state={'suspend':'SUSPENDED','revoke':'REVOKED','resume':'ACTIVE'}[operation]
                if operation=='resume' and db.execute('SELECT state FROM wallets WHERE agent=?',(agent,)).fetchone()[0]=='REVOKED':
                    self._audit(db,'OWNER_DENIED',agent,dict(reason='REVOCATION_PERMANENT'))
                    return {'state':'DENIED','reason':'REVOCATION_PERMANENT'}
                db.execute('UPDATE wallets SET state=? WHERE agent=?',(state,agent))
            elif operation=='approve':
                row = self._tx(db,txid)
                if not row or row['state']!='WAITING_APPROVAL' or self.clock()>=row['expires']:
                    self._audit(db,'OWNER_DENIED',agent,dict(id=txid,reason='NOT_APPROVABLE'))
                    return {'state':'DENIED','reason':'NOT_APPROVABLE'}
                ref='sim-owner-approval:'+uuid.uuid4().hex
                db.execute("UPDATE transactions SET state='AUTHORIZED',approval=? WHERE id=?",(ref,txid))
            elif operation=='refund':
                row=self._tx(db,txid)
                if not row or row['state']!='SETTLED':
                    self._audit(db,'OWNER_DENIED',agent,dict(id=txid,reason='NOT_REFUNDABLE'))
                    return {'state':'DENIED','reason':'NOT_REFUNDABLE'}
                self.provider.refund(db,txid)
                db.execute("UPDATE transactions SET state='REFUNDED' WHERE id=?",(txid,))
            else:
                self._audit(db,'OWNER_DENIED',agent,dict(operation=str(operation)))
                return {'state':'DENIED','reason':'UNKNOWN_CONTROL'}
            self._audit(db,'OWNER_'+operation.upper(),agent,dict(id=txid,value=value))
            return dict(state='APPLIED',operation=operation,mode='SIMULATED')

    def reserve(self, txid, agent):
        with self.connect() as db:
            row=self._tx(db,txid,agent)
            if not row: return {'state':'DENIED','reason':'IDENTITY_MISMATCH'}
            if row['state']!='AUTHORIZED':
                self._audit(db,'RESERVE_NOT_AUTHORIZED',agent,dict(id=txid,state=row['state']))
                return self._receipt(row)
            quote=json.loads(row['request'])['quote']
            reason=self._policy_reason(db,agent,quote,reserve=True)
            if reason:
                db.execute("UPDATE transactions SET state=?,reason=? WHERE id=?",('EXPIRED' if reason=='EXPIRED' else 'DENIED',reason,txid))
            else:
                # Budget period follows the actual reservation/charge, not an
                # earlier request that happened on the other side of midnight.
                db.execute("UPDATE transactions SET state='RESERVED',budget_at=? WHERE id=?",(self.clock(),txid))
            self._audit(db,'RESERVATION_DENIED' if reason else 'RESERVED',agent,dict(id=txid,reason=reason))
            return self._receipt(db.execute('SELECT * FROM transactions WHERE id=?',(txid,)).fetchone())

    def execute(self, txid, agent, *, scenario='success'):
        if scenario not in {'success','outage','timeout','partial','ambiguous_before','ambiguous_after'}:
            raise ValueError('Unknown simulated failure scenario')
        with self.connect() as db:
            row=self._tx(db,txid,agent)
            if not row: return {'state':'DENIED','reason':'IDENTITY_MISMATCH'}
            if row['state']!='RESERVED':
                self._audit(db,'EXECUTE_NOOP',agent,dict(id=txid,state=row['state']))
                return self._receipt(row)
            reason=self._policy_reason(db,agent,json.loads(row['request'])['quote'])
            if reason:
                db.execute("UPDATE transactions SET state=?,reason=? WHERE id=?",('EXPIRED' if reason=='EXPIRED' else 'CANCELLED',reason,txid))
                self._audit(db,'EXECUTION_DENIED',agent,dict(id=txid,reason=reason))
            else:
                self._audit(db,'EXECUTING',agent,dict(id=txid,provider='simulated',scenario=scenario))
                result=dict(service=json.loads(row['request'])['quote']['service'],
                            artifact='Simulated purchased service result',transaction_id=txid,mode='SIMULATED',
                            objective_sha256=hashlib.sha256(json.loads(row['request'])['objective'].encode()).hexdigest(),
                            word_count=len(json.loads(row['request'])['objective'].split()))
                state=self.provider.execute(db,txid,result,scenario)
                db.execute('UPDATE transactions SET state=?,result=?,reason=? WHERE id=?',
                           (state,canonical(result) if state=='SETTLED' else None,'' if state=='SETTLED' else scenario,txid))
                if state=='SETTLED':
                    db.execute('UPDATE transactions SET budget_at=? WHERE id=?',(self.clock(),txid))
                self._audit(db,state,agent,dict(id=txid,provider_response=dict(scenario=scenario,result=result if scenario in {'success','ambiguous_after'} else None)))
            return self._receipt(db.execute('SELECT * FROM transactions WHERE id=?',(txid,)).fetchone())

    def recover(self, txid, agent):
        with self.connect() as db:
            row=self._tx(db,txid,agent)
            if not row: return {'state':'DENIED','reason':'IDENTITY_MISMATCH'}
            provider=self.provider.status(db,txid)
            if row['state']=='INDETERMINATE':
                # Query the original provider record; never invoke a new payment.
                state='SETTLED' if provider and provider['state']=='ACCEPTED' else 'FAILED'
                db.execute('UPDATE transactions SET state=?,result=?,reason=? WHERE id=?',
                           (state,provider['result'] if state=='SETTLED' else None,'resolved-original-provider-status',txid))
                if state=='SETTLED':
                    db.execute('UPDATE transactions SET budget_at=? WHERE id=?',(self.clock(),txid))
            elif row['state'] in {'AUTHORIZED','RESERVED','WAITING_APPROVAL'} and self.clock()>=row['expires']:
                db.execute("UPDATE transactions SET state='EXPIRED',reason='EXPIRED' WHERE id=?",(txid,))
            self._audit(db,'RECONCILED',agent,dict(id=txid,provider_status=provider['state'] if provider else 'SIMULATED_NOT_EXECUTED'))
            return self._receipt(db.execute('SELECT * FROM transactions WHERE id=?',(txid,)).fetchone())

    def cancel(self, txid, agent):
        with self.connect() as db:
            row=self._tx(db,txid,agent)
            if not row: return {'state':'DENIED','reason':'IDENTITY_MISMATCH'}
            if row['state'] in {'AUTHORIZED','RESERVED','WAITING_APPROVAL'}:
                db.execute("UPDATE transactions SET state='CANCELLED' WHERE id=?",(txid,))
            self._audit(db,'CANCEL_REQUESTED',agent,dict(id=txid,previous_state=row['state']))
            return self._receipt(db.execute('SELECT * FROM transactions WHERE id=?',(txid,)).fetchone())

    def report(self):
        with self.connect() as db:
            return dict(balances=self._balances(db),wallets=[dict(row) for row in db.execute('SELECT agent,wallet,state FROM wallets ORDER BY agent')],
                        transactions=[self._receipt(row) for row in db.execute('SELECT * FROM transactions ORDER BY budget_at,id')],
                        audit=[dict(row) for row in db.execute('SELECT * FROM audit ORDER BY seq')],
                        registry_sha256=self.registry_sha, external_providers=EXTERNAL_PROVIDERS,
                        mode='SIMULATED', certification='UNVERIFIED', live_spending='DISABLED')


def authority(root):
    """Explicit candidate opt-in only; never reads real payment credentials."""
    if os.getenv('PRIME_FINANCIAL_SIMULATION_ENABLED','0') != '1':
        raise ValueError('Financial simulation is not enabled')
    root=Path(root)/'financial-simulation'
    root.mkdir(parents=True,exist_ok=True)
    key_path=root/'simulation-audit.key'
    if root.is_symlink() or key_path.is_symlink() or (root/'treasury.sqlite3').is_symlink():
        raise ValueError('Authority store must not be symlinked')
    if not key_path.exists():
        if (root/'treasury.sqlite3').exists():
            raise IntegrityError('Existing treasury audit key is missing; owner recovery required')
        candidate=root/('key-init-'+uuid.uuid4().hex)
        fd=os.open(candidate,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(secrets.token_bytes(32));stream.flush();os.fsync(stream.fileno())
            try:os.link(candidate,key_path)
            except FileExistsError:pass
        finally:
            candidate.unlink()
    return FinancialSimulation(root/'treasury.sqlite3',key_path.read_bytes())


def execute_objective(body, *, actor, task_id, root):
    """Called from the real authenticated capability-owner dispatch path."""
    if (body.classification!='R0' or body.data_classification!='LOCAL_ONLY'
            or body.max_cost_usd!=0 or body.preferred_provider is not None):
        raise ValueError('Simulation requires local-only zero-cost execution')
    finance=authority(root)
    request=json.loads(body.context)
    if type(request) is not dict or request.get('objective')!=body.objective:
        # The actual task cannot pay for a different prompt-supplied objective.
        with finance.connect() as db:
            finance._audit(db,'OBJECTIVE_MISMATCH',actor,dict(task_id=task_id))
        raise ValueError('Financial request must match its owning objective')
    receipt=finance.request(actor,request,task_id)
    if receipt['state']=='AUTHORIZED':
        receipt=finance.reserve(receipt['id'],actor)
        if receipt['state']=='RESERVED': receipt=finance.execute(receipt['id'],actor)
    if 'id' in receipt: receipt=finance.recover(receipt['id'],actor)
    return dict(schema_version='orqevia.financial-simulation.v1',agent_id=actor,
                task_id=task_id,objective=body.objective,receipt=receipt,
                result=receipt.get('result'),model_calls=0,live_spending='DISABLED',certification='UNVERIFIED')
