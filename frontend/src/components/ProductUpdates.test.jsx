import React, { act } from "react";
import { createRoot } from "react-dom/client";
import ProductUpdates from "./ProductUpdates";
import { PRODUCT_UPDATES } from "../lib/productUpdates";
jest.mock("sonner",()=>({toast:jest.fn()}));
jest.mock("./ui/dialog",()=>({Dialog:({open,children})=>open?<div>{children}</div>:null,DialogContent:({children})=><div>{children}</div>,DialogHeader:({children})=><div>{children}</div>,DialogTitle:({children})=><h2>{children}</h2>,DialogDescription:({children})=><p>{children}</p>}));
let root, container;
beforeEach(()=>{global.IS_REACT_ACT_ENVIRONMENT=true;localStorage.clear();container=document.createElement("div");document.body.appendChild(container);root=createRoot(container);});
afterEach(()=>{act(()=>root.unmount());container.remove();});
test("unread updates highlight features and exploration opens the correct workspace",async()=>{
 const explore=jest.fn();await act(async()=>root.render(<ProductUpdates userId="owner" wsId="ws" onExplore={explore}/>));
 expect(container.querySelector("style").textContent).toContain("nav-customers");
 await act(async()=>container.querySelector('button[aria-label="New updates, unread"]').click());
 expect(container.textContent).toContain("Customers & lifetime value");
 await act(async()=>[...container.querySelectorAll("button")].find(b=>b.textContent.includes("Explore feature")).click());
 expect(explore).toHaveBeenCalledWith("/app/w/ws/customers");
 expect(localStorage.getItem("arevei:updates:seen:owner")).toBeNull();
});
test("acknowledgement persists per user and clears feature highlights",async()=>{
 await act(async()=>root.render(<ProductUpdates userId="owner" wsId="ws" onExplore={jest.fn()}/>));
 await act(async()=>container.querySelector("button").click());
 await act(async()=>[...container.querySelectorAll("button")].find(b=>b.textContent==="Mark all as read").click());
 expect(container.querySelector("style")).toBeNull();
 expect(JSON.parse(localStorage.getItem("arevei:updates:seen:owner"))).toEqual(PRODUCT_UPDATES.map(r=>r.id));
 await act(async()=>root.render(<ProductUpdates userId="other" wsId="ws" onExplore={jest.fn()}/>));
 expect(container.querySelector("style")).not.toBeNull();
});
