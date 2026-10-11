import { act } from 'react';
import { createRoot } from 'react-dom/client';
import BrainConversation from './BrainConversation';
import api from '../lib/api';
let mockWorkspace={id:'workspace',brain_status:'error'};
const mockRefresh=jest.fn();
jest.mock('react-router-dom',()=>({useOutletContext:()=>({ws:mockWorkspace,refresh:mockRefresh})}),{virtual:true});
jest.mock('sonner',()=>({toast:{success:jest.fn()}}));
jest.mock('../lib/api',()=>({__esModule:true,formatError:v=>v,default:{get:jest.fn(),post:jest.fn()}}));
const ready={draft:{business_profile:{company_name:'Studio',offers:['Consulting']}},messages:[],revision:2,ready:true,question:null,answered:7,total:7};
let root,container;
beforeEach(()=>{global.IS_REACT_ACT_ENVIRONMENT=true;mockWorkspace={id:'workspace',brain_status:'error'};container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);api.get.mockResolvedValue({data:ready});api.post.mockResolvedValue({data:ready});});
afterEach(()=>{act(()=>root.unmount());container.remove();jest.clearAllMocks();});
test('asks a question and displays polished structured knowledge as readable text',async()=>{
 api.get.mockResolvedValue({data:{...ready,ready:false,question:{field:'audience',text:'Who are your customers?',optional:false}}});
 api.post.mockResolvedValue({data:{...ready,draft:{...ready.draft,audience:{icps:[{name:'Local shops',pains:['Need more enquiries']}]}},messages:[{role:'assistant',content:'Local shops need more enquiries.'}]}});
 await act(async()=>root.render(<BrainConversation/>));
 const input=container.querySelector('textarea');
 await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'local shops need enquiries');input.dispatchEvent(new Event('input',{bubbles:true}));});
 await act(async()=>container.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(api.post).toHaveBeenCalledWith('/workspaces/workspace/brain/conversation',{answer:'local shops need enquiries',field:'audience',revision:2});
 expect(container.textContent).toContain('Local shops');expect(container.textContent).not.toContain('[object Object]');
});
test('publishes the reviewed draft using its revision',async()=>{
 await act(async()=>root.render(<BrainConversation/>));
 await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Complete Brain').click());
 expect(api.post).toHaveBeenCalledWith('/workspaces/workspace/brain/conversation/complete',{revision:2});
 expect(mockRefresh).toHaveBeenCalled();
});
test('prevents completion while website training is running',async()=>{
 mockWorkspace.brain_status='building';
 await act(async()=>root.render(<BrainConversation/>));
 expect([...container.querySelectorAll('button')].find(b=>b.textContent==='Website training in progress').disabled).toBe(true);
});
