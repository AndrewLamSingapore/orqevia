"""Optional explicitly configured task-class caps; no automatic extension/replay.

Each model catalog entry may define task_budgets[class] (or default), containing
output_tokens, context_tokens and timeout_seconds. Optional named extensions are
selected only by selected_extension configuration or reasoning_budget_extension
on a trusted persisted job. The request cannot supply its own cap values.
Every selected budget remains inside model/job limits and existing reserved cost.
"""
from dataclasses import dataclass,replace
from decimal import Decimal,InvalidOperation
import math
from .provider_runtime import ProviderFailure


@dataclass(frozen=True)
class ReasoningBudget:
    model: object
    output_tokens: int
    timeout_seconds: float
    configured: bool
    extension: str | None = None

    def receipt(self):
        return {'configured':self.configured,'output_tokens':self.output_tokens,
                'context_tokens':self.model.context_tokens,'timeout_seconds':self.timeout_seconds,
                'extension':self.extension,'automatic_extension':False}


def select_budget(entry,job,model):
    configured=entry.get('task_budgets')
    if configured is None:
        if job.get('reasoning_budget_extension'):
            raise ProviderFailure('REASONING_BUDGET_EXTENSION_DENIED',pre_execution=True)
        return ReasoningBudget(model,model.output_tokens,job['timeout_seconds'],False)
    if not isinstance(configured,dict):raise ProviderFailure('REASONING_BUDGET_CONFIG_INVALID',pre_execution=True)
    spec=configured.get(job.get('task_class','auto'),configured.get('default'))
    if spec is None:
        if job.get('reasoning_budget_extension'):raise ProviderFailure('REASONING_BUDGET_EXTENSION_DENIED',pre_execution=True)
        return ReasoningBudget(model,model.output_tokens,job['timeout_seconds'],False)
    if not isinstance(spec,dict):raise ProviderFailure('REASONING_BUDGET_CONFIG_INVALID',pre_execution=True)
    extension=job.get('reasoning_budget_extension',spec.get('selected_extension'))
    selected=spec
    if extension is not None:
        options=spec.get('extensions',{})
        if not isinstance(extension,str) or not isinstance(options,dict) or extension not in options:
            raise ProviderFailure('REASONING_BUDGET_EXTENSION_DENIED',pre_execution=True)
        selected=options[extension]
        if not isinstance(selected,dict):raise ProviderFailure('REASONING_BUDGET_CONFIG_INVALID',pre_execution=True)
    try:
        output=selected['output_tokens'];context=selected['context_tokens'];duration=selected['timeout_seconds']
        if type(output) is not int or type(context) is not int or type(duration) not in (int,float):raise ValueError()
        if not 0<output<=model.output_tokens or not output<context<=model.context_tokens:raise ValueError()
        if not math.isfinite(duration) or not 0<duration<=job['timeout_seconds']:raise ValueError()
    except (KeyError,TypeError,ValueError):raise ProviderFailure('REASONING_BUDGET_CONFIG_INVALID',pre_execution=True) from None
    return ReasoningBudget(replace(model,output_tokens=output,context_tokens=context),output,duration,True,extension)


def verify_reserved_cost(budget,job,messages):
    if not budget.configured:return
    model=budget.model
    upper=sum(len(m['content'].encode())+16 for m in messages)
    if upper+budget.output_tokens>model.context_tokens:
        raise ProviderFailure('CONTEXT_BUDGET_EXCEEDED',pre_execution=True)
    if model.input_usd_million is None or model.output_usd_million is None:
        raise ProviderFailure('REASONING_BUDGET_PRICE_UNAVAILABLE',pre_execution=True)
    rate=max(model.input_usd_million,model.cached_usd_million or model.input_usd_million)
    estimate=(Decimal(upper)*rate+Decimal(budget.output_tokens)*model.output_usd_million)/Decimal(1_000_000)
    try:
        reserved=Decimal(str(job.get('estimated_cost_usd',0)));limit=Decimal(str(job.get('max_cost_usd',0)))
        if not reserved.is_finite() or not limit.is_finite() or min(reserved,limit)<estimate:raise ValueError()
    except (ValueError,InvalidOperation):raise ProviderFailure('REASONING_BUDGET_COST_EXCEEDED',pre_execution=True) from None
