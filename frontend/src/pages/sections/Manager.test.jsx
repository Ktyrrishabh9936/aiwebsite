import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import Manager from './Manager';
import api from '../../lib/api';
const mockNav=jest.fn();
jest.mock('react-router-dom',()=>({useNavigate:()=>mockNav,useOutletContext:()=>({ws:{id:'ws',name:'Studio'},refresh:jest.fn()})}),{virtual:true});
jest.mock('../../lib/api',()=>({__esModule:true,default:{get:jest.fn()}}));
jest.mock('../../components/AiStatus',()=>({AiStatus:()=>null,useAiStatus:()=>({state:'ready',run:jest.fn()}),aiErrorMessage:()=>''}));
jest.mock('../../components/SalesBriefing',()=>()=> <div>Live CRM briefing</div>);
jest.mock('../../components/ChatText',()=>({ChatText:({text})=><span>{text}</span>}));
let root,container;
beforeEach(()=>{HTMLElement.prototype.scrollTo=jest.fn();global.IS_REACT_ACT_ENVIRONMENT=true;container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();jest.clearAllMocks();});
async function check(){await act(async()=>root.render(<Manager/>));await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Check Insights').click());}
test('check insights opens the live briefing when CRM has records',async()=>{api.get.mockResolvedValue({data:{total_leads:3}});await check();expect(container.textContent).toContain('Live CRM briefing');expect(api.get).toHaveBeenCalledWith('/workspaces/ws/sales/briefing');});
test('empty CRM guides business training and sales strategy instead of showing insights',async()=>{api.get.mockResolvedValue({data:{total_leads:0}});await check();expect(container.textContent).not.toContain('Live CRM briefing');expect(container.textContent).toContain('There are no leads');await act(async()=>[...container.querySelectorAll('button')].find(b=>b.textContent==='Build sales strategy').click());expect(mockNav).toHaveBeenCalledWith('/app/w/ws/brain?tab=sales');});
