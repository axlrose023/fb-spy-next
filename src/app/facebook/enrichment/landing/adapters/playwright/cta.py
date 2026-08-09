SCROLL_CTA_JS = r"""
(payload) => {
  const GLYPHS=[0xF17E1,0xF078B];
  const DOMAIN_RE=/^(https?:\/\/)?([a-z0-9-]+\.)+[a-z]{2,}(\/\S*)?$/i;
  const PUA=c=>(c>=0xE000&&c<=0xF8FF)||(c>=0xF0000);
  const strip=s=>[...(s||'')].filter(ch=>!PUA(ch.codePointAt(0))).join('').replace(/\s+/g,' ').trim();
  const domain = typeof payload === 'string' ? payload : payload.domain;
  const elementId = typeof payload === 'string' ? '' : (payload.element_id || '');
  for (const old of document.querySelectorAll('[data-fbspy-cta]')) delete old.dataset.fbspyCta;
  const hasGlyph=s=>{for(const sp of s.querySelectorAll('span')){if(!(sp.getAttribute('style')||'').includes('#8a8d91'))continue;for(const ch of(sp.innerText||''))if(GLYPHS.includes(ch.codePointAt(0)))return true;}return false;};
  const words=s=>strip(s).split(/\s+/).filter(Boolean).length;
  const numericLike=s=>/^[\d\s.,+]+([KkMmBb])?$/.test(strip(s).replace(/\s+/g,''));
  const okText=s=>{const tx=strip(s);return tx.length>=2&&tx.length<=42&&words(tx)>=1&&words(tx)<=5&&/[\p{L}]/u.test(tx)&&!/\d/.test(tx)&&!numericLike(tx)&&!DOMAIN_RE.test(tx)&&!/[a-z0-9-]+\.[a-z]{2,}/i.test(tx);};
  const engagementTop=root=>{let top=Infinity;for(const el of root.querySelectorAll('a,[role="button"],[role="link"],[data-action-id]')){const r=el.getBoundingClientRect();const tx=strip(el.innerText);if(r.width>=40&&r.height>=20&&numericLike(tx))top=Math.min(top,r.top);}return top;};
  const bestButton=(root,maxTop=Infinity)=>{let best=null;for(const el of root.querySelectorAll('a,[role="button"],[role="link"],[data-action-id]')){const r=el.getBoundingClientRect();const tx=strip(el.innerText);if(r.top>=maxTop)continue;if(r.width<50||r.height<20||r.height>90||!okText(tx))continue;const score=r.top*10+r.width;if(!best||score>best.score)best={el,score};}return best&&best.el;};
  const markTarget=(target,kind)=>{if(!target)return null;target.scrollIntoView({block:'center'});target.dataset.fbspyCta='1';const r=target.getBoundingClientRect();return{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2),kind};};
  if(elementId){
    const marked=document.querySelector(`[data-fbspy-click-target="${elementId}"]`);
    if(marked)return markTarget(marked,'detected_target');
  }
  const roots = [];
  if (elementId) {
    const exact = document.querySelector(`[data-fbspy-id="${elementId}"]`);
    if (exact) roots.push(exact);
  }
  if (!roots.length) roots.push(...document.querySelectorAll('div'));
  for(const el of roots){
    const t=el.innerText||'';if(t.length<80||t.length>3500)continue;if(!el.querySelector('img')&&!el.querySelector('video'))continue;
    if(el.getBoundingClientRect().width<300)continue;
    if(!hasGlyph(el))continue;
    for(const d of el.querySelectorAll('div')){
      if(hasGlyph(d))continue;
      const dl=(d.innerText||'').split("\n").map(x=>x.trim()).filter(Boolean);
      if(dl.length>=2&&DOMAIN_RE.test(dl[0])){
        const dom=dl[0].replace(/^https?:\/\//,'').split('/')[0].toLowerCase();
        if(dom!==domain)continue;
        let target=bestButton(d, engagementTop(el));
        if(!target){
          for(let node=d,depth=0;node&&node!==el&&depth<5;node=node.parentElement,depth++){
            if(node.matches('a,[role="button"],[role="link"],[data-action-id]')){target=node;break;}
          }
        }
        return markTarget(target,target===d?'link_card':'structural_target');
      }
    }
  }
  return null;
}
"""
