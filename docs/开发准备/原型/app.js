'use strict';
const $ = (id) => document.getElementById(id);
const initial = () => ({page:'story', configured:false, scenario:'normal', project:'雨夜借光', adopted:1, confirmed:true, candidate:false, draft:'外套从芥末黄改为深蓝，保持人物身份和其他镜头不变。', adoptedDescription:'成年年轻女性，黑色短发，芥末黄外套，深青围裙。', subtitleDraft:'别怕，我借你一点光。', task:'idle', spent:0, reserved:0, remaining:600, missingResolved:false, stopped:false});
let state = initial();
let opener = null;
const money = (value) => `¥${(value/100).toFixed(2)}`;
const pages = {story:['01 / 准备制作依据','把故事说清楚','先确认要保留的故事，再制作角色和镜头。'],visual:['02 / 准备资产与分镜','让同一个角色贯穿故事','当前选择与当前采用分开；修改前先看影响。'],video:['03 / 制作当前镜头','先做好这一镜','当前对象：S03 中文对白。只启动这一镜的任务。'],edit:['04 / 声音与剪辑','听清对白，安排节奏','原片、配音和字幕保持各自来源，剪辑修改可预览。'],export:['05 / 检查与导出','确认这一次交付','检查当前采用的素材与版本，再导出本地成片。'],costs:['06 / 项目工具','每一笔费用都有去向','演示账目只用于理解流程，不代表供应商价格。']};
function notify(text){$('notice').textContent=text;}
function button(label, action, primary=false){const element=document.createElement('button');element.textContent=label;if(primary)element.className='primary';element.addEventListener('click',action);return element;}
function close(){ $('modal').close(); if(opener?.isConnected)opener.focus(); }
function dialog(title, body, actions){opener=document.activeElement;$('dialog-title').textContent=title;$('dialog-body').replaceChildren();if(typeof body==='string')$('dialog-body').innerHTML=body;else $('dialog-body').append(body);$('dialog-actions').replaceChildren(...actions);$('modal').showModal();}
function configure(){dialog('准备制作服务','<p>正式产品需要分别配置模型、音频传输和媒体工具。此处仅模拟完整配置，不录入真实 Key。</p><div class="row"><span>文字 / 图像服务</span><span>待配置</span></div><div class="row"><span>正式配音 / 视频 / 音频传输</span><span>待配置</span></div><div class="row"><span>本地 FFmpeg</span><span>待配置</span></div><p class="warning">配置成功与生成质量通过是不同状态。</p>',[button('先浏览本地示例',close),button('模拟配置完成',()=>{state.configured=true;close();render();notify('已模拟配置完成。真实产品仍需独立验证接口、效果与工具。');},true)]);}
function setPage(page){state.page=page;render();}
function actions(...items){const element=document.createElement('div');element.className='actions';element.append(...items);$('workspace').append(element);}
function render(){
  const [step,title,intro]=pages[state.page];$('step-label').textContent=step;$('page-title').textContent=title;$('page-intro').textContent=intro;$('project-name').textContent=state.project;
  document.querySelectorAll('[data-page]').forEach(x=>{if(x.dataset.page===state.page)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current');});
  $('adopted').textContent=`版本 ${state.adopted} · ${state.confirmed?'已确认':'待复检'}`;$('spent').textContent=money(state.spent);$('reserved').textContent=money(state.reserved);$('forecast').textContent=money(state.spent+state.reserved+state.remaining);
  const box=$('workspace');
  if(state.scenario==='disconnected'){
    box.innerHTML='<div class="card"><h3>本地服务连接中断</h3><p>当前输入保留。连接中断不能说明云端任务失败，也不会自动重新生成。</p></div>';
    actions(button('模拟重新连接',()=>{state.scenario='normal';$('scenario').value='normal';render();notify('已模拟重连，只恢复已有状态，没有新增生成。');},true));return;
  }
  if(state.page==='story'){
    box.innerHTML='<div class="grid"><article class="card"><h3>故事梗概</h3><p class="story">雨夜，年轻修理师阿禾发现一只没电的机械猫。她把左手的便携灯放入猫背接口，松开手。灯暗下去，猫的眼灯慢慢亮起，回应她的善意。</p><span class="pill">已有剧本 · 保留原意</span></article><section class="card"><h3>这条片必须讲清楚</h3><ul class="list"><li>阿禾主动借出灯。</li><li>左手放入、松手并撤离。</li><li>机械猫用亮起的眼灯回应。</li><li>完整说出“别怕，我借你一点光。”</li></ul></section></div>';
    actions(button('查看制作配置',configure),button('确认故事，查看分镜',()=>{setPage('visual');notify('故事已在演示中确认；没有自动启动付费生成。');},true));
  }else if(state.page==='visual'){
    box.innerHTML='<div class="grid"><div class="card"><h3>七镜头故事板</h3><img class="film" src="../../资料/图片/七镜头故事板.png" alt="雨夜借光七镜头研究故事板，二维流程示例，非最终写实质量"><small>已有研究素材 · 仅用于流程演示</small></div><div class="card"><h3>阿禾 · 当前采用</h3><p>成年年轻女性，黑色短发，芥末黄外套，深青围裙。</p><p>保持人物身份、便携灯唯一性和左手持灯。</p><div id="candidate-state"></div></div></div>';
    box.querySelector('.grid>.card:last-child>p').textContent=state.adoptedDescription;
    $('candidate-state').textContent=state.candidate?'已准备修改草稿，尚未改变当前采用。':(state.adopted>1?'外套修改已采用；相关视觉成果待复检。参考图仍为旧研究素材。':'当前没有未采用的修改。');
    actions(button('修改角色外套',editDraft),button('查看当前镜头',()=>setPage('video'),true));
  }else if(state.page==='video'){
    box.innerHTML='<div class="grid"><div class="card"><h3>S03 · 阿禾安抚机械猫</h3><p>“别怕，我借你一点光。”</p><video class="film" controls preload="metadata" src="../../资料/视频/对白原始视频.mp4" aria-label="已有研究对白视频，口型与身份质量未通过"></video><small>已有二维研究原片 · 嘴部和身份未通过正式质量验收</small></div><div class="card"><h3>当前任务</h3><p id="task-status"></p><p>输入：已核对关键帧 + 采用配音<br>演示请求：4 秒 / 1 个候选<br>最大演示费用：¥1.20</p><p id="task-warning" class="warning"></p></div></div>';
    const video=box.querySelector('video');
    video.poster='../../资料/图片/对白视频抽帧.png';
    video.addEventListener('error',()=>{const fallback=document.createElement('p');fallback.id='media-fallback';fallback.className='warning';fallback.textContent='当前浏览器无法解码研究视频。请使用支持 H.264 的本地播放器查看原文件。';const link=document.createElement('a');link.href='../../资料/视频/对白原始视频.mp4';link.textContent='查看研究视频原文件';fallback.append(document.createElement('br'),link);video.after(fallback);},{once:true});
    const names={idle:'待启动',unknown:'结果待确认 · 可能已计费',download:'结果待下载 · 原任务已完成',complete:'候选已取回 · 尚未采用'};
    $('task-status').textContent=names[state.task];$('task-warning').textContent=state.stopped?'已停止本地等待；不代表云端取消或退费。':'每次只启动当前镜头，不自动进入下一镜。';
    if(state.task==='idle')actions(button('查看任务与费用',plan,true));
    else if(state.task==='unknown')actions(button('停止等待',stopWaiting),button('查询原任务',()=>{state.task='download';state.stopped=false;render();notify('模拟原任务查询完成。沿用原任务和占用，没有再次生成。');},true));
    else if(state.task==='download')actions(button('停止等待',stopWaiting),button('重新下载原结果',complete,true));
    else actions(button('检查候选后采用',()=>{dialog('采用镜头候选','<p>此演示模拟采用动作。实际研究视频仍未通过正式质量验收，不把本次点击记为质量证据。</p>',[button('返回检查',close),button('模拟采用',()=>{state.confirmed=false;close();setPage('edit');notify('已模拟采用候选，检查状态仍为待复检。');},true)]);},true));
  }else if(state.page==='edit'){
    box.innerHTML='<div class="card"><h3>30 秒时间线</h3><div class="frames"><span>S01<br>4秒</span><span>S02<br>4秒</span><span class="active">S03<br>4秒</span><span>S04<br>5秒</span><span>S05<br>5秒</span><span>S06<br>4秒</span><span>S07<br>4秒</span></div><p>配音：别怕，我借你一点光。</p><label for="subtitle">独立编辑字幕文字</label><input class="full" id="subtitle" value="别怕，我借你一点光。"><small>单改字幕不会自动重新配音。</small><p id="subtitle-diff"></p></div>';
    $('subtitle').value=state.subtitleDraft;
    actions(button('替换 S04 视频',replacePreview),button('保存字幕草稿',()=>{state.subtitleDraft=$('subtitle').value;$('subtitle-diff').textContent='字幕草稿已保存，配音保持原样；采用前可检查文字差异。';notify('字幕修改只影响字幕及相关检查，没有新增语音费用。');}),button('检查与导出',()=>setPage('export'),true));
  }else if(state.page==='export'){
    box.innerHTML='<div class="card"><h3>当前采用链检查</h3><div class="row"><span>画幅 / 帧率 / 时长</span><span class="check">演示结构可检查</span></div><div class="row"><span>研究素材的真实质量</span><span class="warning">未通过正式验收</span></div><div class="row"><span>修改后的相关成果</span><span class="warning">需要复检</span></div><p>正式产品将定位具体问题、补证或采用修订后再复检。无关废弃候选不会阻碍当前导出。</p></div>';
    actions(button('查看待复检项',()=>notify('示例待复检：S03 人物身份和口型；若角色改色，S03/S06 视觉需更新。')),button('查看导出规格',()=>dialog('导出设置预览','<p>1080 × 1920 · 24 fps · H.264 / AAC MP4</p><p>字幕默认烧录；覆盖同名文件需确认。</p><p class="warning">当前为原型，不创建成片。正式导出必须解决当前采用链的必要阻断问题。</p>',[button('返回检查',close,true)]),true));
  }else{
    box.innerHTML='<div class="card"><h3>费用如何计算</h3><p>预计完工总额 = 已花 + 待结算占用 + 未提交制作估算 + 明确返工情景</p><div class="row"><span>当前演示任务</span><span id="cost-detail"></span></div><p>结算后替换占用，不重复相加。失败、未采用、撤销和裁剪不会自动退费。</p><p class="warning">这里的金额是构造示例，不能作为真实模型价格。</p></div>';
    $('cost-detail').textContent=state.task==='idle'?'尚未提交':`${money(state.spent)} 已花 / ${money(state.reserved)} 待结算`;
    actions(button('返回当前镜头',()=>setPage('video'),true));
  }
}
function editDraft(){const content=document.createElement('div');const label=document.createElement('label');label.htmlFor='change-text';label.textContent='希望如何修改';const text=document.createElement('textarea');text.id='change-text';text.value=state.draft;content.append(label,text);dialog('修改角色草稿',content,[button('放弃修改',close),button('预览修改影响',()=>{state.draft=text.value;state.candidate=true;close();impact();},true)]);}
function impact(){const content=document.createElement('div');content.innerHTML='<div class="compare"><div><h3>当前采用</h3><p>版本 1：芥末黄外套</p></div><div><h3>修改草稿</h3><p id="change-preview"></p></div></div><p>受影响：S03、S06 角色视觉及相关检查。无关配音保持。</p><p>额外生成费用尚未估算；采用本地修改不会自动购买新结果。</p>';
content.querySelector('.compare>div:first-child>p').textContent=`版本 ${state.adopted}：${state.adoptedDescription}`;
content.querySelector('#change-preview').textContent=state.draft;dialog('采用前，确认修改影响',content,[button('保留当前版本',()=>{state.candidate=false;close();render();notify('已放弃本次采用，当前版本与费用保持不变。');}),button('采用修改',()=>{state.adopted+=1;state.adoptedDescription=state.draft;state.confirmed=false;state.candidate=false;close();render();notify(`已采用版本 ${state.adopted}。相关视觉待更新，费用未变化。`);},true)]);}
function plan(){
  if(!state.configured){configure();return;}
  if(state.scenario==='budget'){dialog('预算不足','<p>当前阶段演示余额 ¥0.80，本任务需要预留 ¥1.20，缺少 ¥0.40。</p><p>调整预算只改变上限，不会自动执行任务。</p>',[button('返回本地编辑',close),button('模拟调整阶段预算',()=>{state.scenario='normal';$('scenario').value='normal';close();notify('演示预算已调整，尚未提交任务。再次查看计划后才能启动。');},true)]);return;}
  if(state.scenario==='missing'&&!state.missingResolved){dialog('缺少必要参考','<p>S03 首帧参考尚未核对，不能静默改为文生视频。</p>',[button('先保存草稿',close),button('模拟导入并核对',()=>{state.missingResolved=true;close();notify('已模拟参考核对，仍需重新查看任务计划。');},true)]);return;}
  dialog('启动当前镜头任务','<p><strong>S03 · 中文对白</strong></p><p>外发：当前关键帧、采用配音和镜头说明。<br>1 个候选，最多 1 次生成，无额外 AI 预检。<br>4 秒，演示最高费用 ¥1.20。</p><p>失败或结果未知时停止后续提交；再次生成是新任务。</p>',[button('暂不启动',close),button('确认并启动演示任务',()=>{state.reserved=120;state.remaining=Math.max(0,state.remaining-120);state.task=state.scenario==='unknown'?'unknown':state.scenario==='download'?'download':'download';close();render();if(state.scenario==='normal')complete();else notify('演示任务已提交，占用已记录。请使用原任务恢复入口。');},true)]);
}
function complete(){if(state.task==='complete')return;state.task='complete';state.spent+=110;state.reserved=0;state.stopped=false;render();notify('原结果已模拟取回。演示结算 ¥1.10 替换 ¥1.20 占用；候选尚未采用。');}
function stopWaiting(){state.stopped=true;render();notify('只停止本地等待。云端可能继续执行，占用与原任务都保留。');}
function replacePreview(){dialog('替换素材的影响','<p>S04 原剪辑占用 5 秒，新视频只有 3 秒，缺少 2 秒。</p><p>不能自动拉伸、循环或冻结。可保留旧视频，或回到分镜调整时长/安排补拍。</p>',[button('保留旧视频',()=>{close();notify('已保留 S04 原视频和 5 秒剪辑，没有新增生成或修改账目。');},true),button('返回分镜调整',()=>{close();setPage('visual');notify('请在分镜草稿中调整必要动作与时长，再预览采用影响。');})]);}
$('nav').addEventListener('click',event=>{const target=event.target.closest('[data-page]');if(target)setPage(target.dataset.page);});
$('settings').addEventListener('click',configure);$('close-dialog').addEventListener('click',close);
$('modal').addEventListener('cancel',()=>{if(opener?.isConnected)opener.focus();});
$('scenario').addEventListener('change',()=>{state.scenario=$('scenario').value;state.task='idle';state.spent=0;state.reserved=0;state.remaining=600;state.stopped=false;state.missingResolved=false;state.page=state.scenario==='short'?'edit':'video';render();notify('已切换走查情景；演示任务状态已重置。');});
$('reset').addEventListener('click',()=>{state=initial();$('scenario').value='normal';render();notify('演示已重置。');});
$('new-project').addEventListener('click',()=>{dialog('新建演示项目','<label for="new-name">项目名称</label><input id="new-name" class="full" maxlength="120" value="我的第一条漫剧"><p>30 秒 · 9:16 · 1080p / 24 fps。正式产品会让用户选择本地目录，此处不写入文件。</p>',[button('取消',close),button('创建演示项目',()=>{const name=$('new-name').value.trim();if(!name){$('new-name').setCustomValidity('请填写项目名称');$('new-name').reportValidity();return;}state=initial();state.project=name;close();render();notify('演示项目已创建，仍可在未配置模型时浏览本地内容。');},true)]);});
render();
