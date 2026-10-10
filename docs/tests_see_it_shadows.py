"""Shadow clearance check for docs/film.html: every settled scene, every element with a hard offset shadow, the gap between the
shadow's bottom/right edge and the next sibling that has a border or a background must be at least MIN px. Run with the docs folder
served on 8795 (python3 -m http.server 8795 --bind 127.0.0.1). Prints a JSON list of violations; empty means clean."""
import asyncio, json, sys
from playwright.async_api import async_playwright
MIN = 12
SETTLE="document.getAnimations().forEach(a=>{try{if(a.effect&&a.effect.getTiming().iterations!==Infinity)a.finish()}catch(e){}})"
DETECT="""(min)=>{const s=document.querySelector('.scene.active');const els=[...s.querySelectorAll('*')].filter(e=>!e.closest('.ctx'));const hits=[];
 const sh=e=>{const m=getComputedStyle(e).boxShadow.replace(/rgb\\([^)]*\\)/g,'c').match(/(-?\\d+)px\\s+(-?\\d+)px/);return m?{dx:+m[1],dy:+m[2]}:null};
 const solid=o=>{const c=getComputedStyle(o);return parseFloat(c.borderTopWidth)>0||c.backgroundColor!=='rgba(0, 0, 0, 0)'};
 for(const e of els){const d=sh(e);if(!d||(!d.dx&&!d.dy))continue;const r=e.getBoundingClientRect();if(!r.width)continue;
   for(const o of els){if(o===e||e.contains(o)||o.contains(e)||!solid(o))continue;const b=o.getBoundingClientRect();if(!b.width)continue;
     const xo=Math.min(r.right+d.dx,b.right)-Math.max(r.left,b.left)>4, yo=Math.min(r.bottom+d.dy,b.bottom)-Math.max(r.top,b.top)>4;
     const below=b.top-(r.bottom+d.dy), right=b.left-(r.right+d.dx);
     if(xo&&below>=-2&&below<min) hits.push(`${e.className.toString().slice(0,20)} → ${o.className.toString().slice(0,20)}: ${Math.round(below)}px below`);
     if(yo&&right>=-2&&right<min&&b.top<r.bottom&&b.bottom>r.top) hits.push(`${e.className.toString().slice(0,20)} → ${o.className.toString().slice(0,20)}: ${Math.round(right)}px right`);}}
 return {scene:s.getAttribute('aria-label'),hits:[...new Set(hits)]}}"""
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); bad=[]
        for W,H in ((1280,800),(1600,1000)):
            pg=await b.new_page(viewport={"width":W,"height":H}); await pg.goto("http://127.0.0.1:8795/film.html?v=sh"); await pg.wait_for_timeout(400)
            await pg.click("#goSound"); await pg.keyboard.press(' ')
            n=await pg.evaluate("document.querySelectorAll('.scene').length")
            for i in range(n):
                if i: await pg.keyboard.press('ArrowRight')
                await pg.wait_for_timeout(70); await pg.evaluate(SETTLE); await pg.wait_for_timeout(40)
                r=await pg.evaluate(DETECT, MIN)
                if r['hits']: bad.append({f'{W}x{H}': r})
            await pg.close()
        print(json.dumps(bad)); await b.close(); sys.exit(1 if bad else 0)
asyncio.run(main())
