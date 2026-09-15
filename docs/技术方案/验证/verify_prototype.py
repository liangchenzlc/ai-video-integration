"""Internal G00 browser walkthrough, no human/usability or product-runtime claim."""
from pathlib import Path
import json
import tempfile
from playwright.sync_api import sync_playwright

DOCS = Path(__file__).resolve().parents[2]
PROTO = DOCS / '开发准备/原型'

def run():
    result = {'scope': 'internal simulated prototype only', 'passed': False, 'scenarios': [], 'errors': [], 'externalRequests': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--log-file='+str(Path(tempfile.gettempdir())/'ai-video-prototype-chromium.log')])
        page = browser.new_page(viewport={'width':1280, 'height':800})
        page.on('pageerror', lambda error: result['errors'].append(str(error)))
        page.on('console', lambda msg: result['errors'].append(msg.text) if msg.type == 'error' else None)
        page.on('request', lambda request: result['externalRequests'].append(request.url) if request.url.startswith(('https://','http://')) else None)
        page.goto((PROTO/'index.html').as_uri())
        def click(text):
            page.get_by_role('button',name=text,exact=True).click()
        def contains(selector, text):
            assert text in page.locator(selector).inner_text(), (selector, text)
        def scenario(name):
            page.locator('#scenario').select_option(name)
        def submit():
            click('查看任务与费用')
            click('确认并启动演示任务')
        click('新建演示项目');page.locator('#new-name').fill('内部走查项目');click('创建演示项目');contains('#project-name','内部走查项目')
        result['scenarios'].append('G01 create local example without provider')
        click('制作配置');click('模拟配置完成');result['scenarios'].append('G02 configuration explanation')
        click('视觉与分镜');click('修改角色外套');page.locator('#change-text').fill('外套改为深蓝');click('预览修改影响');click('保留当前版本');contains('#adopted','版本 1')
        click('修改角色外套');click('预览修改影响');click('采用修改');contains('#adopted','版本 2');contains('#adopted','待复检');contains('#spent','¥0.00');contains('#workspace','外套改为深蓝')
        result['scenarios'].append('G03 discard and adopt maintain cost')
        click('镜头制作')
        page.wait_for_function('document.querySelector("video").readyState >= 1 || document.querySelector("video").error !== null')
        result['mediaPreview'] = page.locator('video').evaluate('(v)=>({metadataAvailable:v.readyState>=1,errorCode:v.error?v.error.code:null})')
        if result['mediaPreview']['errorCode'] is not None:
            contains('#media-fallback','无法解码')
            result['mediaPreview']['fallbackVerified'] = True
        submit();contains('#spent','¥1.10');contains('#reserved','¥0.00');contains('#task-status','尚未采用');result['scenarios'].append('G04 one task settles once')
        scenario('unknown');submit();contains('#reserved','¥1.20');click('停止等待');contains('#reserved','¥1.20');contains('#task-warning','不代表云端取消');click('查询原任务');contains('#task-status','待下载');click('重新下载原结果');contains('#spent','¥1.10');contains('#reserved','¥0.00');result['scenarios'].append('G05/G06 unknown, stop waiting, original query/download')
        scenario('download');submit();contains('#task-status','待下载');click('重新下载原结果');contains('#spent','¥1.10');result['scenarios'].append('G06 download failure recovery')
        scenario('budget');click('查看任务与费用');contains('#dialog-body','缺少 ¥0.40');click('模拟调整阶段预算');contains('#task-status','待启动');contains('#reserved','¥0.00');result['scenarios'].append('G07 budget adjustment does not submit')
        scenario('missing');click('查看任务与费用');contains('#dialog-title','必要参考');click('模拟导入并核对');contains('#task-status','待启动');result['scenarios'].append('G08 reference missing blocks task')
        scenario('short');click('替换 S04 视频');contains('#dialog-body','缺少 2 秒');click('保留旧视频');contains('#notice','5 秒');result['scenarios'].append('G09 short replacement preserves original')
        page.locator('#subtitle').fill('别怕，我借你一些光。');click('保存字幕草稿');contains('#notice','没有新增语音费用');click('故事');click('声音与剪辑');assert page.locator('#subtitle').input_value() == '别怕，我借你一些光。';result['scenarios'].append('G10 subtitle edit persists across navigation and keeps speech cost')
        scenario('disconnected');contains('#workspace','本地服务连接中断');click('模拟重新连接');contains('#notice','没有新增生成');result['scenarios'].append('G11 disconnect/reconnect')
        click('检查与导出');click('查看导出规格');contains('#dialog-body','不创建成片');page.keyboard.press('Escape');assert not page.locator('#modal').is_visible();result['scenarios'].append('G12 export preview and Escape')
        click('视觉与分镜')
        (PROTO/'screenshots').mkdir(exist_ok=True)
        page.screenshot(path=str(PROTO/'screenshots/desktop.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.set_viewport_size({'width':375,'height':812});page.screenshot(path=str(PROTO/'screenshots/narrow.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.keyboard.press('Tab')
        assert page.evaluate("document.activeElement.tagName !== 'BODY'")
        assert not result['errors'], result['errors']
        assert not result['externalRequests'], result['externalRequests']
        result['passed'] = True
        browser.close()
    return result

if __name__ == '__main__':
    try:
        outcome = run()
    except Exception as error:
        outcome = {'scope': 'internal simulated prototype only', 'passed': False, 'error': str(error)}
    (DOCS/'开发准备/prototype-validation.json').write_text(json.dumps(outcome,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(outcome,ensure_ascii=False,indent=2))
    raise SystemExit(0 if outcome['passed'] else 1)
