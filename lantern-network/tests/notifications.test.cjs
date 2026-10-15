const test=require('node:test');
const assert=require('node:assert/strict');
const LanternNotifier=require('../web/notifications.js');
function setup({permission='granted',enabled=true,alerts=[{id:1,ip:'192.168.1.2',message:'A new device appeared'}]}={}){
 const notifications=[],requests=[];
 class Notification {
  static permission=permission;
  static async requestPermission(){return this.permission;}
  constructor(title,options){notifications.push({title,options});}
 }
 let stored=String(enabled);
 const storage={getItem:()=>stored,setItem:(_,v)=>stored=v};
 const request=async(...args)=>{requests.push(args);return {alerts};};
 return {notifier:new LanternNotifier(request,storage,Notification),notifications,requests};
}
const state={demo:false,config:{network:'192.168.1.0/24'},alerts:[{read:0,notified:0}]};
test('delivery needs explicit browser opt-in and permission',async()=>{
 for(const settings of [{enabled:false},{permission:'denied'},{permission:'default'}]){
  const {notifier,requests}=setup(settings);await notifier.deliver(state);assert.equal(requests.length,0);
 }
});
test('multiple alerts produce one desktop digest with a stable scope tag',async()=>{
 const {notifier,notifications,requests}=setup({alerts:[{ip:'192.168.1.2',message:'New device'},{ip:'192.168.1.3'}]});
 await notifier.deliver(state);assert.equal(requests.length,1);assert.equal(notifications.length,1);
 assert.match(notifications[0].title,/2 network updates/);
 assert.equal(notifications[0].options.tag,'lantern-192.168.1.0/24');
});
test('already-read or claimed alerts are not requested',async()=>{
 const {notifier,requests}=setup();await notifier.deliver({...state,alerts:[{read:1,notified:0},{read:0,notified:1}]});assert.equal(requests.length,0);
});
test('unsupported browsers and denied permission keep inbox usable',async()=>{
 const notifier=new LanternNotifier(()=>{}, {getItem:()=>null},null);
 assert.equal(notifier.permission,'unsupported');await assert.rejects(()=>notifier.enable(),/not supported/);
 const {notifier:denied}=setup({enabled:false,permission:'denied'});await assert.rejects(()=>denied.enable(),/not allowed/);assert.equal(denied.enabled,false);
});
test('claim failures release the busy flag for retry',async()=>{
 const {notifier}=setup();notifier.request=async()=>{throw new Error('Offline');};
 await assert.rejects(()=>notifier.deliver(state),/Offline/);assert.equal(notifier.busy,false);
});
test('parallel delivery calls make one claim and demo is labeled',async()=>{
 const {notifier,requests,notifications}=setup();await Promise.all([notifier.deliver({...state,demo:true}),notifier.deliver(state)]);
 assert.equal(requests.length,1);assert.match(notifications[0].title,/^Demo/);
});
