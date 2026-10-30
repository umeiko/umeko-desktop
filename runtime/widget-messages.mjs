// Widget updates use Pi's native custom-message delivery, never a second tool.
export function createWidgetMessages({getSession,emit}) {
  const seen=new Map();
  function receipt(id,status,error) {
    seen.set(id,status);
    if(seen.size>1000)seen.delete(seen.keys().next().value);
    emit({type:'widget_delivery',id,status,...(error?{error:String(error).slice(0,1000)}:{})});
  }
  function observe(event) {
    const message=event.message;
    if(event.type==='message_start' && message?.role==='custom' && message.customType==='umeko-widget-update' && seen.has(message.details?.widgetEventId))
      receipt(message.details.widgetEventId,'delivered');
  }
  async function deliver(update) {
    if(!update || !/^[a-f0-9]{32}$/.test(update.id || '') || typeof update.message!=='string' || !update.message.trim() || [...update.message].length>8000 || typeof update.widgetId!=='string' || !update.data || typeof update.data!=='object' || Array.isArray(update.data))throw new Error('Invalid Widget update');
    if(JSON.stringify(update).length>65536)throw new Error('Widget update exceeds limit');
    if(seen.has(update.id)){receipt(update.id,seen.get(update.id));return;}
    const session=getSession();
    if(!session)throw new Error('Pi session is not ready');
    const content=`Widget update from ${update.name || update.widgetId} (${update.widgetId}). This is application data for the current conversation.\n`+
      `Message ID: ${update.id}\nRequest ID: ${update.requestId || '(unsolicited update)'}\n${update.message}\nStructured data:\n${JSON.stringify(update.data)}`;
    receipt(update.id,'queued');
    try {
      await session.sendCustomMessage({customType:'umeko-widget-update',content,display:true,
        details:{widgetEventId:update.id,widgetId:update.widgetId,requestId:update.requestId || '',data:update.data}},
        {deliverAs:'steer',triggerTurn:update.wake!==false});
    } catch(error){receipt(update.id,'failed',error.message);throw error;}
  }
  return {deliver,observe};
}
