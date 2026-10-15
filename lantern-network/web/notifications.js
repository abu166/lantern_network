'use strict';
/** Desktop delivery is optional; persistent alerts remain in SQLite regardless. */
class LanternNotifier {
 constructor(request, storage, NotificationAPI) {
  this.request=request;this.storage=storage;this.NotificationAPI=NotificationAPI;this.busy=false;
 }
 get enabled(){try{return this.storage.getItem('lantern.desktop')==='true';}catch{return false;}}
 get permission(){return this.NotificationAPI?.permission||'unsupported';}
 setEnabled(value){try{this.storage.setItem('lantern.desktop',String(value));}catch{throw new Error('Browser storage is unavailable. Desktop notifications could not be enabled.');}}
 async enable(){
  if(!this.NotificationAPI)throw new Error('Desktop notifications are not supported in this browser. Use the alert inbox.');
  const permission=await this.NotificationAPI.requestPermission();
  if(permission!=='granted')throw new Error('Notifications were not allowed. You can still use the alert inbox.');
  this.setEnabled(true);
 }
 async deliver(state){
  if(this.busy||!this.enabled||this.permission!=='granted'||!state.alerts.some(a=>!a.read&&!a.notified))return;
  this.busy=true;
  try{
   const {alerts}=await this.request('alerts/claim','POST',{});
   if(!alerts.length)return;
   const prefix=state.demo?'Demo · ':'';
   const latest=alerts[0],name=latest.label||latest.hostname||latest.ip;
   const notification=new this.NotificationAPI(prefix+(alerts.length===1?'Lantern · Network update':`Lantern · ${alerts.length} network updates`),{
    body:alerts.length===1?`${name}${latest.room?' · '+latest.room:''}: ${latest.message}`:`${name}: ${latest.message}. Open Lantern to review all ${alerts.length} alerts.`,
    tag:`lantern-${state.demo?'demo':state.config.network}`,icon:'/favicon.svg',
   });
   notification.onclick=()=>{window.focus();window.location.hash='alerts';notification.close();};
  }finally{this.busy=false;}
 }
}
if(typeof module!=='undefined')module.exports=LanternNotifier;
