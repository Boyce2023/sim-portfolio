# 飞书原生文档标杆规格与上传链路核验技术规范（NTRA Wave 2 专用）

## 总结论
`飞书原生文档创建与上传链路已全线打通，主线程在 Wave 2 可直接复用现有工具链一键建档并零报错上传。`
经对标杆文档《LLY 礼来 · 2026Q3 财报纪要与模型指引核验》（`obj_token: Tg1bdMm4YokRmZxNUlvcOIoJn4d`）、Buwen 亲笔《DUOL 主文档》及 Semi Research 知识库实测核验：
1. **节点挂载目标**：新建文档挂载于 Semi Research（`space_id: 7668584996113796343`）下的 `Natera (NTRA)` 节点（`wiki_token: HmmBw07heiDs4ekuKFFcR91hnhg`，父节点为 `AI4Bio` `O02Iws6mKiSAxxkVQ6VcLhknnbh`）。现有 9 篇子文档运行完好，新建文档可直接作为第 10 篇兄弟节点写入。
2. **权限主体**：Buwen 飞书身份为 `邓卜文`（`open_id: ou_aed97673bae5046d05af1a95f4e55838`，`user_id: 3a5bee28`）。本地 token 脚本已委托其个人身份运行，新建文档所有权自动归属 Buwen，亦可调用 Drive 权限 API 显式赋予编辑权限。
3. **上传稳定性保证**：已彻底理清图片上传三步法（`block_type: 27`）、大表降维与分卷策略（列数上限 8 列、块数上限 460 块）、黄色高亮（`background_color: 3`）、以及 `Doctype` 导致第 0 行溢出字面量 `html` 的底层诱因。写作严格执行标点与过程词两重防火墙，确保一次通过。

---

## 一、标杆文档结构与语言风格拆解

### 1. LLY 礼来标杆文档规格参数
- **文档标题**：`LLY 礼来 · 2026Q3 财报纪要与模型指引核验`
- **总块数与分布**：共 477 个 Block。包含 245 个文本块（`block_type: 2`）、7 个二级标题（`block_type: 4`）、8 个无序列表项（`block_type: 12`）、1 个分割线（`block_type: 22`）、4 张高清原图（`block_type: 27`）、3 张大表格（`block_type: 31`，含 208 个单元格 `block_type: 32`）。
- **标题层级规范**：
  - 根节点：文档标题（Type 1，Page）
  - 一级章节：统一采用二级标题（Type 4，Heading 2），共 7 章：
    - `财报核心速览`
    - `一、股价复盘与三季报成色`
    - `二、销量来源与渗透率上限`
    - `三、净价跌幅与经营杠杆`
    - `四、代谢代际接力与非代谢支柱`
    - `五、指引还原与三年回报测算`
    - `六、电话会关键原话核查`
- **第 1 章速览标准版式**：
  - 开头紧跟 8 个带粗体前缀的 Bullet 项：`发布时间：`、`总体定性：`、`超预期项（Beat）：`、`不到预期项（Miss）：`、`全年指引变化：`、`对估值影响：`、`实际股价波动：`、`前景与未来 3 年单年涨幅（CAGR）：`。
  - 核心定性与 3 年复合回报直接用反引号高亮（黄底 `background_color: 3`），数字精确到个位数与小数点后一位。
- **高亮句（黄底）密度与标准**：
  - 全篇共 16 处文本标记了 `background_color: 3`，占总文本块约 6.5%。
  - 高亮句标准：只标核心定量结论、超市场预期差的核心机制、估值上修幅度与熊市压力测试底线。严禁给背景事实或泛泛描述打高亮。
- **表格列数与字数控制**：
  - 标杆 3 张表格全部严格控制在 8 列以内（列数：8、8、8）。
  - 实测列宽数组：`[319, 76, 76, 101, 83, 91, 434, 79]`、`[620, 76, 76, 76, 83, 91, 83, 76]`、`[620, 83, 83, 83, 83, 83, 83, 79]`。
  - 第一列为指标名称（较宽，300 至 620px），中间各列为数值或比例（紧凑，76 至 101px），倒数第二列为口径调整说明（较宽），最后一列为数字性质三标签（`事实`、`推算`、`事实与推算`）。
- **尾部电话会核查标准（C2 铁律）**：
  - 高管姓名与职务（英汉对照）｜ 电话会场次，日期
  - 英文原话（双引号包裹，完整无删节）
  - 中文翻译（精准买方信达雅，单句 15 至 40 字）

### 2. DUOL Buwen 亲笔文档风格精髓
- **第一句直接定性资产性质与估值洼地**：`Duolingo是个软件股，做语言学习，现金牛，手头现金是营收的4.5倍，在过去两年被压到了非常低的估值。`
- **第二句直面市场分歧与核心焦虑**：`市场担忧是两件事，第一产品力不够好...第二是AI可以轻松替代...`
- **微观供给侧扎根**：深入物理层参数，如国家级转化率对比（日本品牌认知度从不足 5% 到 20%，韩国 DAU 保持 150% 增速，印度手机内存限制与 20MB 安装包），拒绝空洞买方黑话。
- **图表穿插逻辑**：在论点转折与核心争议点直接插入图表标记（`A_price.png`、`B_yoy.png`），以图证史。

---

## 二、知识库节点拓扑与建档赋权方案

### 1. Semi Research 知识库拓扑现状
- **知识库 ID（Space ID）**：`7668584996113796343`
- **根分类节点**：`AI4Bio`（`node_token: O02Iws6mKiSAxxkVQ6VcLhknnbh`，`obj_token: IHjNdLkReo0mMSxL7kec2UbfnQv`）
- **标的父节点**：`Natera (NTRA)`
  - `node_token`: `HmmBw07heiDs4ekuKFFcR91hnhg`
  - `obj_token`: `U5rTdmjqloC00xx2JBfcTRxEnbg`
  - `owner`: `ou_aed97673bae5046d05af1a95f4e55838`
- **NTRA 节点下现有 9 篇子文档**：
  1. `关于TAM的考虑`（`node_token: CdtAwcuo0iJdOXk7AjUcSq70nMd`）
  2. `claude_NTRA 一页纸`（`node_token: FP73wYbPjiHyPKkqBw2c0tTrnhd`）
  3. `claude_NTRA 医学翻译手册与患者旅程`（`node_token: BfBEwrv8uigMkmkB072cUG4In5d`）
  4. `claude_NTRA 底稿一 这门生意与它的账`（`node_token: Inr3wa4p3iJCZ8kx2yXcypibnsf`）
  5. `claude_NTRA 底稿二 单价从 1275 到 2000 美元`（`node_token: WkFGwXokQiyAklkwsZic5Mvsn9c`）
  6. `claude_NTRA 底稿三 壁垒、竞争与 AI`（`node_token: A3L7wuYIki3ozwkl22ycRcJWnZd`）
  7. `claude_NTRA 底稿四 十年后的 Natera`（`node_token: CPMvwzLcCi19p2kiLwtctW4QnVe`）
  8. `claude_NTRA 两年复盘与逐季旁批`（`node_token: PRrywbJIGiqpafkXkDccwvTBnhe`）
  9. `claude_NTRA 医生与患者声音`（`node_token: WVMRw2BPkixwbJkXi6hcMsPGn5d`）

### 2. 新建独立文档接口与参数
在 `Natera (NTRA)` 节点下新建独立 Wiki 文档：
```python
POST https://open.feishu.cn/open-apis/wiki/v2/spaces/7668584996113796343/nodes
Headers:
  Authorization: Bearer <user_access_token>
  Content-Type: application/json
Body:
{
  "obj_type": "docx",
  "node_type": "origin",
  "title": "NTRA Natera · 深度研究主报告与估值模型核验",
  "parent_node_token": "HmmBw07heiDs4ekuKFFcR91hnhg"
}
```
返回载荷包含新建节点的 `node_token` 与对应的 `obj_token`（即后续 `docx` 写入的 `doc_id`）。

### 3. Buwen 编辑权限赋予方案
Buwen 飞书个人账号信息：
- 姓名：`邓卜文`
- `open_id`: `ou_aed97673bae5046d05af1a95f4e55838`
- `user_id`: `3a5bee28`
- `union_id`: `on_927227d51f994fbf1fe053c3beeda8e3`

由于建档调用的是由 Buwen 授权的委托 User Token，新文档默认 Creator 与 Owner 均是 Buwen 本人。为防御性确保协作权限，可显式调用 Drive Permission API：
```python
POST https://open.feishu.cn/open-apis/drive/v1/permissions/{obj_token}/members?type=docx&need_notification=false
Headers:
  Authorization: Bearer <user_access_token>
  Content-Type: application/json
Body:
{
  "member_type": "openid",
  "member_id": "ou_aed97673bae5046d05af1a95f4e55838",
  "perm": "edit",
  "perm_type": "container"
}
```

---

## 三、飞书 API 写入链路与实测技术指标

### 1. Token 统一获取与进程防冲撞锁
- 唯一 Token 脚本路径：`/Users/huaichuaibeimeng/.claude/session-remote/feishu_token.py`
- 串行锁与缓存机制：
  - 本地缓存文件 `/tmp/.feishu_at_cache.json` 记录 `at` 与过期时间戳 `exp`（留 5 分钟缓冲）。
  - 文件排他锁 `/tmp/.feishu_refresh.lock` 防止多进程并发刷新导致飞书单次有效 `refresh_token` 互相作废。
  - 调用入口：直接引入 `html2feishu.py` 内部的 `_shared_tok()` 函数。

### 2. 块批量写入策略（Children API）
- 普通文本、标题、列表项、分割线走批处理接口：
  `POST https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children`
- **批次大小约束**：实测单批建议控制在 38 至 40 个 Block，批次间休眠 `0.32s`，避免触发飞书频控（`99991400`）。

### 3. 表格与 Descendant 写入限制
- 表格（Type 31）及其单元格（Type 32）与内部文本（Type 2）属于复合结构，必须调用 Descendant 接口：
  `POST https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/descendant`
- **单表总块数上限（460 块硬红线）**：
  飞书接口单次处理块上限约为 500 个。对于一张 $R$ 行 $C$ 列的表格，需要 $1 + 2 \times R \times C$ 个块。
  必须调用 `split_big_tables()`：若单表块数超 460，自动按行切分为多卷，每卷保留相同表头。
- **宽表切分策略（8 列硬红线）**：
  调用 `split_wide_tables_in_items(..., max_cols=8)`：若表格列数大于 8 列，固定保留第 0 列作为主键列，将其余数据列按 7 列一批拆为多个分卷，并在分卷前插入说明段落 `（宽表分卷 X/Y）`。
- **实测自适应列宽算法（Text PX）**：
  飞书 12px 单元格实测渲染参数：中文字符约 12.2px，西文字符约 6.8px，单元格边距与边框共 18px。
  最小列宽 `MINW = 76px`，最大列宽 `MAXW = 620px`。总宽度根据列数自适应分布在 960px 至 1500px 之间，避免换行与过度拉伸。
- **严禁表中表与 Callout 嵌套表格**：
  飞书底层不允许 Callout（Type 19）内部包含表格或嵌套 Callout，否则会抛出 `1770030 invalid parent children relation` 错误。`sanitize_callouts()` 会自动将表格和内部 Callout 提升为外部兄弟节点。

### 4. 高清图片内嵌管道（3 步法，Block Type 27）
图片插入必须分为三个顺序步骤：
1. **创建占位块**：
   调用 Children API 创建一个空的图片块：
   `POST .../blocks/{doc_id}/children`，载荷 `{"children": [{"block_type": 27, "image": {}}], "index": -1}`。
   从返回数据中提取新建的块 ID `blk_id`。
2. **上传二进制媒体**：
   通过 `curl` 或 `requests` 发起 Multipart 上传：
   `POST https://open.feishu.cn/open-apis/drive/v1/medias/upload_all`
   表单字段：
   - `file_name`: 图片文件名
   - `parent_type`: `"docx_image"`
   - `parent_node`: `blk_id`
   - `size`: 真实文件字节大小
   - `file`: 二进制文件数据（`image/png`）
   提取返回中的 `file_token`。
3. **替换图片块**：
   调用 Patch 接口关联素材：
   `PATCH https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{blk_id}`
   载荷：`{"replace_image": {"token": file_token}}`。

### 5. 黄底高亮句实现（Background Color 3）
在飞书 docx 的 TextRun 数据结构中，高亮由 `text_element_style` 的 `background_color` 字段控制：
```json
{
  "text_run": {
    "content": "核心判断句内容",
    "text_element_style": {
      "background_color": 3,
      "bold": false
    }
  }
}
```
在 HTML 源码中，只要使用 `<mark>核心判断句</mark>`、`<code>核心判断句</code>` 或带有 `class="hl"` 的标签，解析器均会自动将其映射为 `background_color: 3`。

### 6. 避开 `<!DOCTYPE html>` 导致第 0 行多出字面量 `html` 的诱因与根治方案
- **病根剖析**：
  BeautifulSoup 在解析 HTML 时，会将 `<!DOCTYPE html>` 识别为 `bs4.element.Doctype` 对象。
  如果遍历文本时使用了朴素的 `soup.find_all(text=True)` 或 `soup.strings` 而未对节点类型进行过滤，`Doctype` 会被当成普通字符串提取出来，其文本值恰恰就是 `"html"`。这会导致解析出的第一个段落为 `<p>html</p>`，上传后在飞书文档第 0 行留下难看的孤立单词 `html`。
- **根治方案**：
  在 HTML 预处理中执行双重防御：
  1. 正则预清洗：在解析前使用正则直接将 DOCTYPE 剥离：
     `html_clean = re.sub(r'<!DOCTYPE[^>]*>', '', raw_html, flags=re.I)`
  2. BeautifulSoup 节点显式剔除：
     ```python
     for elem in soup.find_all(string=True):
         if isinstance(elem, (Doctype, Comment)):
             elem.extract()
             continue
     ```

---

## 四、拦截正则与质检网关清单（零拦截通行标准）

### 1. `trace_gate.py` 交付物过程词拦截清单（37 个禁用词）
一旦文本中包含以下任何一个词汇，网关将直接拒绝并阻断发布：
```python
BAN = [
    '交叉核对后', '核对结果', '认可值', '认可通电', '认可 ', 
    '本次核对', '本次新发现', '这次核对', '这次把', '新发现的', 
    '迁自', '搬来', '原样保留', '脚本', '重跑', 
    '重建时', '收尾', '审计发现', '审计漏', '漏剔', 
    '待改', '待核', '改前', '归档版', '交付门', 
    '重算', '研究线', '本项目复核', '已收尾', '合并进了', 
    '没有删除', 'panorama_finish', 'panorama_analysis', 
    'aidc_panorama', 'model_v2_build', 'subagent', 'workflow'
]
```
**写作对策**：文档必须作为一份纯粹的、完成态的最终专业买方报告输出。严禁出现任何施工遗迹、自言自语、审计记录或工作流术语。

### 2. `feishu_upload_verifier.py` 标点与表情拦截清单
- **禁用状态 Emoji（15 个）**：
  `["✅", "⚠️", "⛔", "🔴", "🟢", "🟡", "⭐", "★", "☆", "📌", "💡", "🔥", "🚀", "❌", "📁"]`
  飞书文档正文必须使用纯正买方排版，禁止使用状态符号与花哨表情。
- **禁用标点符号（6 类）及替换规则**：
  1. `——`（双破折号）或 `—`（破折号）$\rightarrow$ 全部替换为中文逗号 `，` 或冒号 `：`。
  2. `–`（En-dash）$\rightarrow$ 替换为范围连接词 `至`。
  3. `→`（箭头）$\rightarrow$ 替换为动词 `至`、`升至`、`转为` 或 `变为`。
  4. `-`（连字符/减号）：
     - 数字负号：`(?<![A-Za-z0-9])-(\d+(?:\.\d+)?%?)` $\rightarrow$ 替换为汉字 `负\1`（例如 `-12%` 改为 `负12%`）。
     - 数字区间：`(\d)-(\d)` $\rightarrow$ 替换为 `\1至\2`（例如 `3-5倍` 改为 `3至5倍`）。
     - 英文词间连字符：`([A-Za-z])-([A-Za-z])` $\rightarrow$ 替换为空格（例如 `head-to-head` 改为 `head to head`）。
     - 孤立连字符：一律剔除或替换为空格。
  5. `！` 与 `!`（感叹号）$\rightarrow$ 全部替换为句号 `。`。严禁在买方报告中使用感叹语气。
- **终审硬指标**：
  上传完毕后调用 `audit_feishu_doc()` 回读检查，`bad_counts` 必须全部为 0：
  `{"-": 0, "—": 0, "——": 0, "！": 0, "!": 0, "→": 0}`。

---

## 五、Wave 2 一键建档与上传执行清单（SOP）

Wave 2 主线程在生成 HTML 与对应图表后，执行以下标准三步即可完成端到端发布：

### Step 1：生成符合规范的中间 HTML
- 核心章节采用 `<h2>` 结构。
- 重点判断句用 `<mark>重点句</mark>` 包裹。
- 表格宽度控制在 8 列以内，超宽自动拆表，最后一列添加事实/推算标签。
- 图表统一采用 `<div class="chart-box"><img src="/path/to/chart.png"/><div class="chart-caption">图表标题</div></div>`。
- 文本全局预清洗，杜绝任何破折号、感叹号、负号连字符与状态 Emoji。

### Step 2：调用建档 API 创建 Wiki 节点
```python
from _tools.feishu_html_with_images import mknode

# 在 Natera 父节点下新建文档
node_info, err = mknode(
    title="NTRA Natera · 深度研究主报告与估值模型核验",
    parent="HmmBw07heiDs4ekuKFFcR91hnhg"
)
node_token, obj_token = node_info
print(f"Node Created: node_token={node_token}, doc_id={obj_token}")
```

### Step 3：调用增强型上传与质检引擎
```bash
python3 /Users/huaichuaibeimeng/claude-projects/docs/90_内部_给Claude读/NTRA_参考/feishu_upload_verifier.py <obj_token> <path_to_clean_html>
```
该脚本将自动执行：
1. 本地 HTML 正则脱敏与 `Doctype` 剔除；
2. 清空目标文档（清空旧残留）；
3. 提取所有本地 PNG 图片并按顺序上传（3 步法关联）；
4. 宽表 8 列拆分与长表 460 块拆分；
5. 批量推送正文、标题与表格；
6. 回读全量 Block，输出词数、图表数、表格数、高亮数及零违禁标点审计报告。
