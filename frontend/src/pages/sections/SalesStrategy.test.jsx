import { act } from "react";
import { createRoot } from "react-dom/client";
import SalesStrategy from "./SalesStrategy";
import api from "../../lib/api";
let mockWorkspace = {id:'workspace',name:'Studio',brain_status:'ready',currency:'INR',sales_profile:{organisation:'Studio',offerings:'Consulting',ideal_customer:'Agencies',team_capacity:'Two salespeople',monthly_revenue_target:200000,business_stage:'existing'}};
const mockRefresh=jest.fn();
jest.mock('react-router-dom',()=>({Link:({to,children,...props})=><a href={to} {...props}>{children}</a>,useOutletContext:()=>({ws:mockWorkspace,refresh:mockRefresh})}),{virtual:true});
jest.mock('../../components/SalesBriefing',()=>()=>null);
jest.mock('sonner',()=>({toast:{success:jest.fn(),error:jest.fn()}}));
jest.mock('../../lib/api',()=>({__esModule:true,formatError:v=>v,default:{put:jest.fn(),post:jest.fn()}}));
let root,container;
beforeEach(()=>{global.IS_REACT_ACT_ENVIRONMENT=true;container=document.createElement('div');document.body.appendChild(container);root=createRoot(container);api.put.mockResolvedValue({data:{}});api.post.mockResolvedValue({data:{}});});
afterEach(()=>{act(()=>root.unmount());container.remove();jest.clearAllMocks();});
test('saves sales context with voice skipped without changing calling configuration',async()=>{
 await act(async()=>root.render(<SalesStrategy/>));
 await act(async()=>container.querySelector('form').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));
 expect(api.put).toHaveBeenCalledWith('/workspaces/workspace/sales/profile',expect.objectContaining({organisation:'Studio',voice_setup:'skipped',monthly_revenue_target:200000}));
 expect(api.post).not.toHaveBeenCalled();
 expect(mockRefresh).toHaveBeenCalled();
});
test('prepares a sales strategy using saved context and prevents generation before brain training',async()=>{
 await act(async()=>root.render(<SalesStrategy/>));
 const prepare=[...container.querySelectorAll('button')].find(b=>b.textContent==='Prepare sales strategy');
 await act(async()=>prepare.click());
 expect(api.post).toHaveBeenCalledWith('/workspaces/workspace/sales/strategy');
 mockWorkspace={...mockWorkspace,brain_status:'building'};
 await act(async()=>root.render(<SalesStrategy/>));
 expect([...container.querySelectorAll('button')].find(b=>b.textContent==='Prepare sales strategy').disabled).toBe(true);
});
