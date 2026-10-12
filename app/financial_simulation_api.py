"""Candidate simulation controls; existing owner authentication is mandatory."""
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from .agent_registry import responsibility_owner, RegistryError
from .client_auth import authenticate_owner
from .financial_simulation import authority, IntegrityError

router=APIRouter(prefix='/api/financial-simulation',tags=['financial-simulation'])


def trusted(authorization):
    authenticate_owner(authorization)
    try:
        return authority(Path(os.getenv('PRIME_DATA_DIR','/data')))
    except (ValueError, IntegrityError) as exc:
        raise HTTPException(503,str(exc)) from None


def actor(capability):
    try:
        return responsibility_owner(capability)
    except RegistryError as exc:
        raise HTTPException(422,str(exc)) from None


class QuoteRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    capability: str = Field(min_length=1,max_length=100)
    service: str = Field(min_length=1,max_length=100)


@router.get('/services')
def services(capability: str, authorization: str | None=Header(None)):
    finance=trusted(authorization)
    return {'mode':'SIMULATED','services':finance.discover(actor(capability)),
            'live_spending':'DISABLED'}


@router.post('/quote')
def quote(body: QuoteRequest, authorization: str | None=Header(None)):
    finance=trusted(authorization)
    try:
        return finance.quote(actor(body.capability),body.service)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None


class OwnerControl(BaseModel):
    model_config=ConfigDict(extra='forbid')
    operation: Literal['freeze','suspend','revoke','resume','approve','refund']
    capability: str | None = Field(default=None,max_length=100)
    transaction_id: str | None = Field(default=None,max_length=32)
    value: bool | None = None


@router.post('/owner-control')
def control(body: OwnerControl, authorization: str | None=Header(None)):
    finance=trusted(authorization)
    return finance.owner_control(body.operation,agent=actor(body.capability) if body.capability else None,
                                 txid=body.transaction_id,value=body.value)


class TransactionControl(BaseModel):
    model_config=ConfigDict(extra='forbid')
    capability: str = Field(min_length=1,max_length=100)
    transaction_id: str = Field(min_length=32,max_length=32)
    operation: Literal['reserve','execute','recover','cancel']


@router.post('/transaction')
def transaction(body: TransactionControl, authorization: str | None=Header(None)):
    finance=trusted(authorization)
    return getattr(finance,body.operation)(body.transaction_id,actor(body.capability))


@router.get('/report')
def report(authorization: str | None=Header(None)):
    return trusted(authorization).report()
