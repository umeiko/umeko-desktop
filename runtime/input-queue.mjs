// One queue policy for desktop parent and child conversations. Pi owns native
// follow-ups; priority input aborts the current run before the next prompt.
export function createInputQueue({getSession,isRunning,onQueue=()=>{},onEdited=()=>{},onReturned=()=>{},beforeInterrupt=()=>{}}) {
  let chain=Promise.resolve(), items=[], adding, interrupts=[], epoch=0;
  function sync(steering,followUp) {
    const previous=[...items];
    items=[["steering",steering],["followUp",followUp]].flatMap(([mode,texts])=>texts.map(text=>{
      const index=previous.findIndex(item=>item.nativeText===text && item.mode===mode);
      const item=index>=0 ? previous.splice(index,1)[0] : adding || {id:crypto.randomUUID(),text,images:[]};
      return {...item,nativeText:text,mode};
    }));
    onQueue(steering,followUp,items.map(({id,text,mode})=>({id,text,mode})));
  }
  function publish() {
    const session=getSession();
    sync(session.getSteeringMessages(),session.getFollowUpMessages());
  }
  async function enqueue(item,mode="followUp") {
    adding={...item,id:item.id || crypto.randomUUID()};
    try { await getSession()[mode==="steering" ? "steer" : "followUp"](item.text,item.images || []); }
    finally { adding=undefined; }
  }
  function take() {
    const pending=[...items];
    items=[];
    getSession().clearQueue();
    return pending;
  }
  function returnQueue() {
    const pending=[...take(),...interrupts.splice(0)];
    if (pending.length) onReturned(pending);
  }
  function cancel() { epoch++; returnQueue(); }
  function submit(input) {
    const token=epoch;
    const work=chain.then(async()=>{
      if (token!==epoch) throw new Error("当前任务已停止，请重新发送这条消息");
      const session=getSession();
      if (!session) throw new Error("Pi 尚未就绪");
      if (["steer","promote-queue","steer-queued"].includes(input.type)) {
        if (!isRunning()) throw new Error("当前任务已结束，请重新发送这条消息");
        const selected=input.type==="steer" ? {id:input.messageId,text:input.text,images:input.images || []}
          : input.type==="promote-queue" ? items[0] : items.find(item=>item.id===input.id);
        if (!selected) throw new Error("这条消息已经开始处理");
        const remaining=take().filter(item=>item!==selected);
        interrupts.push(selected);
        beforeInterrupt();
        await session.abort();
        if (token===epoch) for (const item of remaining) await enqueue(item);
        else if (remaining.length) onReturned(remaining);
      } else if (["edit-queue","delete-queue"].includes(input.type)) {
        const selected=items.find(item=>item.id===input.id);
        if (!selected) throw new Error("这条消息已经开始处理");
        const pending=take();
        if (input.type==="edit-queue") onEdited(selected);
        for (const item of pending) if (item!==selected) await enqueue(item);
      } else if (["follow-up","native-steer"].includes(input.type)) {
        if (!isRunning() || session.isIdle) throw new Error("当前任务已结束，请重新发送这条消息");
        await enqueue({id:input.messageId,text:input.text,images:input.images || []},input.type==="native-steer" ? "steering" : "followUp");
      } else throw new Error("未知的排队操作");
    });
    chain=work.catch(()=>{});
    return work;
  }
  async function run(first,invoke) {
    const token=epoch;
    let next=first;
    do {
      try { await invoke(next); }
      catch (error) { if (!interrupts.length) throw error; }
      await chain;
      next=token===epoch ? interrupts.shift() : undefined;
    } while (next);
  }
  return {sync,publish,submit,run,returnQueue,cancel,
    get chain(){return chain;}, get items(){return items;},
    get hasInterrupts(){return interrupts.length>0;}, shiftInterrupt:()=>interrupts.shift()};
}
