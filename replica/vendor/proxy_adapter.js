// Narrow adapter for the pinned lottie-web 5.13.0 Canvas state stack.
// The shipped opacity() computes the product in its stack, but assigns only the
// local factor to nativeContext.globalAlpha. Keep both representations consistent.
window.installProxyAdapter = function (animation) {
  if (lottie.version !== '5.13.0') throw new Error('Opacity adapter requires verified lottie-web 5.13.0');
  const renderer = animation.renderer;
  const context = renderer.contextData;
  if (!context || !Array.isArray(context.stack) || typeof context.setOpacity !== 'function') {
    throw new Error('Unsupported Canvas context stack');
  }
  renderer.ctxOpacity = function (opacity) {
    const inherited = context.stack[context.cArrPos].opacity;
    const combined=(inherited < 0 ? 1 : inherited) * Math.max(0, opacity);
    context.setOpacity(combined);
    context.nativeContext.globalAlpha=combined;
    context.currentOpacity=combined;
  };
  renderer.renderFrame(animation.currentFrame, true);
  return {name:'multiply-inherited-opacity',lottieVersion:lottie.version};
};

// Experimental exact-value mode: remove the history-dependent 1e-5 assignment
// deadband in scalar/vector animated properties. Keep Float32 storage semantics.
window.installExactValueAdapter = function(animation) {
  if(lottie.version!=='5.13.0')throw new Error('Exact-value adapter requires 5.13.0');
  const renderer=animation.renderer,patched=new WeakSet();let count=0;
  function walk(node,seen){
    if(!node||typeof node!=='object'||seen.has(node))return;
    seen.add(node);
    if(!patched.has(node)&&typeof node.setVValue==='function'&&['unidimensional','multidimensional'].includes(node.propType)){
      node.setVValue=function(value){
        if(this.propType==='unidimensional'){
          const next=value*this.mult;
          if(this.v!==next){this.v=next;this._mdf=true;}
        }else{
          for(let i=0;i<this.v.length;i++){
            const old=this.v[i];this.v[i]=value[i]*this.mult;
            if(old!==this.v[i])this._mdf=true;
          }
        }
      };
      patched.add(node);count++;
    }
    for(const key of ['dynamicProperties','elements'])if(Array.isArray(node[key]))for(const item of node[key])walk(item,seen);
  }
  const render=renderer.renderFrame.bind(renderer);
  renderer.renderFrame=function(frame,force){
    walk(renderer,new Set());const before=count;
    const result=render(frame,force);walk(renderer,new Set());
    if(count>before)render(frame,true);
    return result;
  };
  walk(renderer,new Set());renderer.renderFrame(animation.currentFrame,true);
  return {name:'exact-value-assignment',initialPatchedProperties:count};
};

// Experimental: preserve straight mask edges as lines instead of degenerate cubics.
window.installStraightMaskAdapter=function(animation){
  if(lottie.version!=='5.13.0')throw Error('Straight mask adapter requires 5.13.0');
  const patched=new WeakSet();let count=0;
  const same=(a,b)=>a[0]===b[0]&&a[1]===b[1];
  const straight=(p,a,b)=>same(p.o[a],p.v[a])&&same(p.i[b],p.v[b]);
  function walk(element){
    if(!element)return;
    const m=element.maskManager;
    if(m&&!patched.has(m)&&m.masksProperties.length){
      if(m.masksProperties.some(p=>p.mode!=='a'||p.inv))throw Error('Straight mask adapter supports non-inverted ADD only');
      if(typeof m.drawPath==='function'){
        m.drawPath=function(data,p,view){
          let d='M'+p.v[0].join(',');
          for(let b=1;b<=p._length;b++){
            if(b===p._length&&!p.c)break;
            const a=b-1,j=b%p._length;
            d+=straight(p,a,j)?'L'+p.v[j].join(','):'C'+p.o[a].join(',')+' '+p.i[j].join(',')+' '+p.v[j].join(',');
          }
          if(view.elem)view.elem.setAttribute('d',p.c?d:'');view.lastPath=d;
        };
        for(let i=0;i<m.viewData.length;i++)m.drawPath(m.masksProperties[i],m.viewData[i].prop.v,m.viewData[i]);
      }else{
        m.renderFrame=function(){
          if(!this.hasMasks)return;
          const ctx=this.element.canvasContext,tr=this.element.finalTransform.mat;ctx.beginPath();
          for(const prop of this.viewData){
            const p=prop.v,first=tr.applyToPointArray(...p.v[0],0);ctx.moveTo(first[0],first[1]);
            for(let b=1;b<=p._length;b++){
              const a=b-1,j=b%p._length;
              if(straight(p,a,j)){const end=tr.applyToPointArray(...p.v[j],0);ctx.lineTo(end[0],end[1]);}
              else{const pts=tr.applyToTriplePoints(p.o[a],p.i[j],p.v[j]);ctx.bezierCurveTo(...pts);}
            }
          }
          this.element.globalData.renderer.save(true);ctx.clip();
        };
      }
      patched.add(m);count++;
    }
    for(const child of element.elements||[])walk(child);
  }
  const renderer=animation.renderer,render=renderer.renderFrame.bind(renderer);
  renderer.renderFrame=function(frame,force){walk(renderer);return render(frame,force);};
  walk(renderer);renderer.renderFrame(animation.currentFrame,true);
  return {name:'straight-mask-edges',initialPatchedMasks:count};
};
