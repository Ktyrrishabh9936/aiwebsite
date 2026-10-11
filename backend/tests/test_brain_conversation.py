import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from bson import ObjectId
from fastapi import HTTPException
import pytest
import brain_conversation as chat

WS = ObjectId()
def workspace():
    return {'_id':WS,'brain_status':'error','brain':{'_source_url':'https://example.com','_pages_crawled':['https://example.com'], 'organization':{'bank_details':'Existing bank', 'invoice_prefix':'INV'}}}

def test_state_preserves_source_knowledge_and_asks_for_missing_topics():
    ws=workspace();ws['brain']['business_profile']={'company_name':'Studio','description':'Consulting'}
    current=chat.state(ws)
    assert current['question']['field']=='brand_identity'
    assert current['draft']['organization']['bank_details']=='Existing bank'
    assert not current['ready']

def test_shape_rejects_wrong_lists_and_unapproved_fields():
    assert chat.validate_shape({'offers':['Consulting']},chat.SCHEMAS['business_profile'])
    assert not chat.validate_shape({'offers':'Consulting'},chat.SCHEMAS['business_profile'])
    assert not chat.validate_shape({'bank_details':'Invented'},chat.SCHEMAS['organization'])


def test_answer_persists_only_patches_and_keeps_active_brain_unchanged(monkeypatch):
    import llm_service
    async def run():
        ws=workspace();ws['brain']['business_profile']={'company_name':'Studio','industry':'Old industry'}
        db=SimpleNamespace(workspaces=AsyncMock());db.workspaces.update_one.return_value=SimpleNamespace(matched_count=1)
        monkeypatch.setattr(chat,'access',AsyncMock(return_value=(db,ws)))
        monkeypatch.setattr(llm_service,'generate_json',AsyncMock(return_value={'value':{'description':'Website design for local businesses'}}))
        result=await chat.answer_conversation(str(WS),None,chat.Answer(field='business_profile',answer='we build websites',revision=0))
        assert result['draft']['business_profile']['company_name']=='Studio'
        update=db.workspaces.update_one.call_args.args[1]['$set']
        assert 'brain' not in update
        assert update['brain_conversation']['draft']['business_profile']=={'description':'Website design for local businesses'}
        ws['brain_conversation']=update['brain_conversation']
        ws['brain']['business_profile']['industry']='Refreshed industry'
        assert chat.state(ws)['draft']['business_profile']['industry']=='Refreshed industry'
        with pytest.raises(HTTPException) as stale:
            await chat.answer_conversation(str(WS),None,chat.Answer(field='audience',answer='local shops',revision=0))
        assert stale.value.status_code==409
    asyncio.run(run())


def test_completion_preserves_metadata_and_document_settings(monkeypatch):
    async def run():
        ws=workspace();ws['brain_conversation']={'revision':3,'acknowledged':list(chat.TOPICS),'draft':{'business_profile':{'company_name':'Studio'}}}
        db=SimpleNamespace(workspaces=AsyncMock());db.workspaces.update_one.return_value=SimpleNamespace(matched_count=1)
        monkeypatch.setattr(chat,'access',AsyncMock(return_value=(db,ws)))
        await chat.complete_conversation(str(WS),None,chat.Complete(revision=3))
        patch=db.workspaces.update_one.call_args.args[1]['$set']
        assert patch['brain_status']=='ready'
        assert patch['brain']['_source_url']=='https://example.com'
        assert patch['brain']['_pages_crawled']==['https://example.com']
        assert patch['brain']['organization']['bank_details']=='Existing bank'
        ws['brain_status']='building'
        with pytest.raises(HTTPException) as building:
            await chat.complete_conversation(str(WS),None,chat.Complete(revision=3))
        assert building.value.status_code==409
    asyncio.run(run())


def test_skipping_evidence_does_not_invent_testimonials(monkeypatch):
    async def run():
        ws=workspace();db=SimpleNamespace(workspaces=AsyncMock());db.workspaces.update_one.return_value=SimpleNamespace(matched_count=1)
        monkeypatch.setattr(chat,'access',AsyncMock(return_value=(db,ws)))
        result=await chat.answer_conversation(str(WS),None,chat.Answer(field='evidence',answer='skip',revision=0))
        assert result['draft']['evidence']=={}
        assert 'evidence' in db.workspaces.update_one.call_args.args[1]['$set']['brain_conversation']['acknowledged']
    asyncio.run(run())
