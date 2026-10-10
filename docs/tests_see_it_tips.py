"""Tooltip check for docs/film.html (served on 8795): every .tip shows #tipbox on hover with its text, inside the viewport,
and clicking a tip does not advance the scene. Prints a JSON summary; exit 1 on any failure."""
import asyncio, json, sys
from playwright.async_api import async_playwright
SETTLE="document.getAnimations().forEach(a=>{try{if(a.effect&&a.effect.getTiming().iterations!==Infinity)a.finish()}catch(e){}})"
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await b.new_page(viewport={"width":1440,"height":900}); errs=[]; pg.on('pageerror',lambda e:errs.append(str(e)))
        await pg.goto("http://127.0.0.1:8795/film.html?v=tips"); await pg.wait_for_timeout(400); await pg.click("#goSound"); await pg.keyboard.press(' ')
        n=await pg.evaluate("document.querySelectorAll('.scene').length"); res=[]; bad=[]
        for i in range(n):
            if i: await pg.keyboard.press('ArrowRight')
            await pg.wait_for_timeout(70); await pg.evaluate(SETTLE); await pg.wait_for_timeout(40)
            tips=await pg.query_selector_all('.scene.active .tip')
            for t in tips:
                await t.hover(); await pg.wait_for_timeout(40)
                r=await pg.evaluate("(()=>{const b=document.getElementById('tipbox'),r=b.getBoundingClientRect();return {shown:getComputedStyle(b).display!=='none',text:b.textContent.slice(0,40),inside:r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight}})()")
                snip=await t.inner_text(); res.append(snip)
                if not (r['shown'] and r['text'] and r['inside']): bad.append({'tip':snip,**r})
            if tips:
                before=await pg.evaluate("document.querySelector('.scene.active').getAttribute('aria-label')")
                await tips[0].click(); await pg.wait_for_timeout(120)
                after=await pg.evaluate("document.querySelector('.scene.active').getAttribute('aria-label')")
                if before!=after: bad.append({'click_advanced':before})
                await pg.keyboard.press('Escape')
        print(json.dumps({'tips_checked':len(res),'bad':bad,'errors':errs})); await b.close(); sys.exit(1 if bad or errs else 0)
asyncio.run(main())
