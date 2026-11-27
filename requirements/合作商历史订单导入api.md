# 历史订单导入接口契约

- 日期：2026-11-25；设计稿，接口尚未实现。
- 关联：[技术方案](plan.md)、[建表 SQL](schema.sql)。
- 本服务共 6 个接口，路径前缀为 `/DJEASYORDER/order/v2/`，均为 POST。JSON 请求使用 `Content-Type: application/json`，调用沿用现有登录凭据，身份从可信上下文取得。
- 普通响应沿用 `HttpResult<T>`：`success/code/msg/data`；分页 data 为 `PageResult<T>`：`total/list`。以下响应示例只展示 data，成功 code/msg 由现有框架统一产生，不新造 HTTP 包装。
- 时间字符串使用北京时间 `yyyy-MM-dd HH:mm:ss`，日期使用 `yyyy-MM-dd`。业务 ID、金额、面积及尺寸用字符串返回。无值用 null，列表为空用 []。
- 接口字段名称是本次设计契约；真实产品及大数据 URL/字段由接口提供方对接后落实。
- Controller 类级路径为 `order/v2`，`/DJEASYORDER` 为应用上下文。外部服务调用以对方真实路径为准。

## 1. 提交异步导入

`POST /DJEASYORDER/order/v2/importHistoryOrder.do`

```json
{
  "fileUrl": "/example/history-orders/example.xlsx"
}
```

| 字段 | 类型 | 必填 | 规则 |
| --- | --- | --- | --- |
| fileUrl | string | 是 | 文件服务返回的相对对象地址，最长1024字符，只能一个文件；仅 xls/xlsx，实际内容也需校验；示例路径不代表真实上传地址 |

后端校验有效登录和历史订单导入权限。此权限覆盖导入任务内的客户建档及产品上架，无需另授新增客户或产品上架权限。文件完整暂存后、业务处理前先查询真实供应商已上架产品；合格行匹配到已上架产品时直接复用，仅未匹配产品调用批量上架。前端只提交文件地址，无需传上架选项或配置功能开关。产品服务调用失败按第 7.1 节反馈在导入结果中。

后端在创建任务前按第 7.3 节查询一次真实供应商单位，true→mm、false→cm，保存为任务size_unit及订单单位快照。请求不再声明sizeUnit，额外传入也不能覆盖查询结果。查询失败、超时、data/showUnitmm缺失时返回UNIT_QUERY_FAILED，未创建任务；不默认按cm处理。

上传继续使用现有文件上传能力，本接口不直接接收 MultipartFile。后端校验文件归属，禁止任意公网 URL。文件地址按真实公司防重，即使首次任务失败或供应商单位配置后来变更，也提示重复；重新上传新地址允许导入。

同一真实供应商同时只允许一个未结束的导入任务，范围覆盖该供应商所有用户。后端按可信真实供应商 ID 获取 Redis 分布式提交锁，在锁内检查是否已有 `QUEUED/RUNNING` 任务并创建新任务，任务事务提交后才释放锁。锁竞争或已有未结束任务时返回 `IMPORT_BUSY`，提示“当前供应商有导入任务待处理或正在导入，请稍后再试”，不新建任务排队。Redis 异常返回 `IMPORT_LOCK_UNAVAILABLE`，本次不受理；请求仍只传 `fileUrl`，`file_key` 由后端计算并保留数据库唯一约束。

供应商提交锁释放后，数据库中的未结束任务继续占用导入名额；只有本地状态变为 `SUCCESS/PARTIAL/FAILED` 才允许新任务。线程池满或等待重投的 `QUEUED` 同样占用名额。不同真实供应商可并行，报告生成和大数据同步不阻塞下一次导入。前一任务终结后，相同地址仍按原规则拒绝，重新上传的新地址可受理。

返回：

```json
{
  "taskId": "example-import-task",
  "localStatus": "QUEUED"
}
```

受理表示任务已持久化。前端关闭上传弹窗、打开导入记录，轮询导入记录分页接口的当前页。后台检查文件格式、表头、完整性和是否为空，将非空行每批最多 500 条写入暂存表，整份文件暂存完成后才分批处理。单文件不设业务行数上限，文件大小和 Excel 格式限制仍适用。

登录失效、缺少历史订单导入权限、供应商单位查询失败、文件地址无效或越权、供应商导入忙、Redis 锁不可用、重复地址、文件已知大小超限时，接口同步拒绝。获锁后先检查供应商是否有未结束任务，忙时统一返回 IMPORT_BUSY，不返回其他用户的 taskId 或操作信息。无未结束任务时再检查重复地址；仅当原任务为当前用户创建时，重复地址错误data才可包含原taskId，其他创建人的任务只提示文件已导入，不返回其taskId或操作信息。

## 2. 下载模板

`POST /DJEASYORDER/order/v2/downloadHistoryOrderTemplate.do`，body `{}`。

成功返回 xlsx 文件流，Content-Type 为 `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`，Content-Disposition 使用 UTF-8 `filename*`，建议文件名“历史订单导入模板.xlsx”。

后端通过 `SysParamService.getParamConfig(EASY_ORDER_HISTORY_ORDER_TEMPLATE_URL)` 取得正式模板地址；未配置/不存在/读取失败返回现有错误封装，不返回空文件假成功。读取成功前不提前提交下载响应，流均关闭；已开始传输后的异常由客户端下载失败处理。

模板第一行固定 15 列：客户名称、手机号、材料名称、层数、楞型、落料长、落料宽、片数、平方单价、总面积、总金额、下单时间、收货人、收货地址、业务员。单位由后端按真实供应商查询，导入弹窗不再选择或传入单位，模板不加单位列。

## 3. 历史订单分页

`POST /DJEASYORDER/order/v2/getHistoryOrderList.do`

```json
{
  "pageNo": 1,
  "pageSize": 20,
  "orderDateStart": "2026-01-01",
  "orderDateEnd": "2026-06-30",
  "customerName": "示例客户",
  "phone": "138",
  "materialName": "示例材料"
}
```

pageNo/pageSize 必填，页码≥1，pageSize=1～100。筛选全部可省略；日期成对传、开始≤结束，包含整个结束日。客户名称/手机号/材料名称为 trim 后 contains 模糊匹配，不解析用户通配符；长度上限分别200/32/200。无日期时也只查询当前页。

data：`{"total": 1, "list": [HistoryOrderVo]}`。默认 `order_time DESC,rowid DESC`。

| HistoryOrderVo字段 | 类型 | 含义 |
| --- | --- | --- |
| id | string | 订单业务 ID |
| taskId | string | 原导入任务 ID |
| orderNo | string | YDLH 开头的订单号 |
| infoId | string | 本地客户 ID；联合销售主体导入时指向联合客户 |
| customerId | string | 易网客户 ID，与本地 infoId 区分 |
| customerName | string | 该行 Excel 客户名称快照，不随档案更新 |
| phone | string | 该行 Excel 手机号快照，不随档案更新 |
| materialName | string | Excel 材料名称原值快照 |
| layer | string | Excel 层数原值快照 |
| flute | string | Excel 楞型原值快照 |
| productName | string 或 null | 产品服务确认的名称。PRODUCT_EXISTS 未返回名称时为 null，材料名称仍由 materialName 展示 |
| materialLength | string | 输入落料长，展示时带 sizeUnit，不擅自换算 |
| materialWidth | string | 输入落料宽，展示时带 sizeUnit，不擅自换算 |
| sizeUnit | string | 尺寸单位 cm 或 mm，沿用导入任务的单位快照 |
| pieceNumber | integer | 片数，正整数 |
| squareUnitPrice | string | 平方单价，空输入已变为 0 |
| orderArea | string | 总面积，单位平方米，空输入已变为 0 |
| orderAmount | string | 总金额，单位元，空输入已变为 0 |
| orderTime | string | 有效下单时间，空输入已取任务创建时间 |
| businessCreateTime | string | 业务创建时间，与 orderTime 相同 |
| payTime | string | 业务支付时间，与 orderTime 相同，仅表示历史分析时间 |
| orderStatus | string | 固定 COMPLETED，展示“已完成” |
| receiver | string 或 null | Excel 收货人快照 |
| deliveryAddress | string | Excel 收货地址快照 |
| createTime | string | 本服务实际入库审计时间 |

仅查询 `skey=当前真实公司 && isdel=0`。不展示导入失败行，不混入旧线下订单列表。若历史成功订单已全部被删除，本任务导入成功数不追减。

列表不返回 branchNumber、salesmanName、canDelete；删除权限及来源任务终态仍由删除接口校验。按产品最新确认，列表也不返回压线方式、纵压，不预留空值字段；导入模板保持原 15 列。

## 4. 导入记录分页

按最新 UI 确认，仅保留分页接口，返回操作人、操作时间、操作结果、错误报告可用信息及导入进度，不提供单独的导入记录详情接口。

`POST /DJEASYORDER/order/v2/getImportTaskList.do`

```json
{"pageNo":1,"pageSize":20}
```

pageNo、pageSize 必填，页码至少为 1，pageSize 为 1～100。列表和总数均按当前真实公司和登录用户 ID 过滤，再按 `create_time DESC,rowid DESC` 分页。先查询本地当前页，再为该页符合条件的任务查询大数据同步进度，返回 `{"total":1,"list":[HistoryOrderTaskVo]}`。不接收客户端指定的 taskId 或公司、操作人参数来扩展查询范围。

list 中每条 `HistoryOrderTaskVo` 返回以下字段：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| taskId | string | 导入任务 ID |
| operatorName | string | 任务提交时的操作人姓名快照 |
| createTime | string | 任务提交时间 |
| totalCount | integer 或 null | 完整暂存后的非空行数；文件未完整暂存时为 null |
| successCount | integer | 已提交的成功订单数，不因后续逻辑删除追减 |
| failCount | integer 或 null | 任务未结束时为 null；任务结束且总数已知时为 totalCount - successCount，含中断时尚未处理的行；文件级失败未取得总数时为 0 |
| customerCreatedCount | integer | 本地已确认的客户新增数，联合客户两侧算一组 |
| productCreatedCount | integer | 本任务已确认的产品新增数，已有产品复用不计入新增 |
| localStatus | string | QUEUED 排队待执行；RUNNING 暂存或处理数据中；SUCCESS 正常结束且全部行成功；PARTIAL 正常结束且部分行成功；FAILED 全部行失败、文件校验失败或任务异常中断，中断时可能已有成功订单。独立于报告及大数据进度 |
| reportStatus | string | NONE 尚未满足生成条件或无需报告；BUILDING 报告生成或上传中，含恢复重建；READY 已上传可下载；FAILED 生成或上传失败。报告失败不改变 localStatus |
| errorMessage | string 或 null | 脱敏的文件级或导入任务级失败原因，如表头不符、文件无法读取、任务中断；无此类错误为 null。行级原因通过错误报告查看，报告及大数据进度失败不覆盖该字段 |
| canDownloadErrorReport | boolean | 当前任务有可下载报告，使用 taskId 调用错误报告下载接口 |
| syncedCount | integer 或 null | 取大数据 statistics_order_cnt，含已取消的订单即逻辑删除记录。正常范围为 0 到 successCount，不落库 |

“操作结果”由 totalCount、successCount、failCount、customerCreatedCount、productCreatedCount 组合展示，例如“导入50条，成功45条，失败5条；创建客户档案0家，产品档案0条”。本地未结束时按 localStatus 展示排队或导入中，尚未确定的计数不填成 0；文件级失败通过 errorMessage 展示。报告按 reportStatus 和 canDownloadErrorReport 显示生成中、失败或下载入口。不再返回 fileName、sizeUnit、processedCount。

“导入进度”取自 `/ybill/import_order/statistics_progress`。仅当前页本地已终结且 successCount 大于 0 的任务逐条查询，使用本地查出的 taskId，不查询页外或其他用户的任务。仍在本地导入时 syncedCount=null，显示本地排队或导入中；终结且无成功订单时返回 0，无需调用大数据，显示“无成功订单，无需同步”，不计算 0/0。其余任务以 syncedCount / successCount 展示统计进度，例如 40/45；分母为本地成功数，不是原文件总数。

单条大数据请求失败、超时、缺失计数或计数越界时，该条 syncedCount=null，显示“同步进度暂不可用”，其余计数、其他任务、分页 total/list 和报告信息照常返回；正常返回 0 必须保留为 0。只在本地查询事务结束后请求大数据。当前外部契约仅支持单个 task_id，不虚构批量参数；每个符合条件的任务每次分页请求最多查询一次。设置单次短超时和整页总耗时预算（建议 3 秒，联调校准），单次超时不得超过剩余预算，预算耗尽后未查询的任务返回 syncedCount=null，不无限叠加超时或自动重试；不新增缓存、后台进度任务或无界线程池。

存在扫描延迟。前端仅在弹窗打开时刷新当前页，关闭弹窗停止轮询；当前页任务均本地终结、报告不在生成且进度已完成或无需同步时可停止自动刷新。已提交订单即使遇到后续任务中断，也会被大数据定时扫描。暂存表和报告保留每行结果，分页只返回任务汇总及本次进度。

## 5. 下载错误报告

`POST /DJEASYORDER/order/v2/downloadErrorReport.do`，body `{"taskId":"example-import-task"}`。

只有当前真实公司内、由当前用户创建的 IMPORT 任务，且 `reportStatus=READY` 时才允许下载。其他用户的 taskId 按 TASK_NOT_FOUND 处理。成功返回“历史订单导入错误报告.xlsx”。原始 15 列保持名称和顺序，末尾追加“错误原因”。`FAILED` 行输出保存的具体原因，多项用换行连接。任务中断后 `PENDING` 行标注“任务中断，未提交最终处理结果”。`SUCCESS` 行始终排除，包括后来逻辑删除的订单对应行。

模板不符、文件大小超限、无法读取等文件级错误通过任务 errorMessage 展示。文件未完整暂存时无需逐行报告。BUILDING 返回报告尚未就绪，FAILED 返回报告生成失败，NONE 返回无报告。后台可重传仍存在的报告，或在暂存保留期内从暂存表恢复原始行及已记录原因。重建无需原 Excel，也不重新导入。

## 6. 批量删除历史订单

`POST /DJEASYORDER/order/v2/deleteHistoryOrder.do`

```json
{"ids":["example-order-a","example-order-b"]}
```

ids 必填，1～500 项，每项非空且最长 64 字符。去重后核对全部目标属于当前真实公司且来源导入任务已终结。其他公司、缺失或来源未终结时整批拒绝。已逻辑删除且归属正确的目标视为已完成，重复请求不会覆盖原删除记录。

成功返回 `{"deletedCount":2}`，为本次实际由有效改为已删除的订单数。前端提交成功后刷新订单列表。删除只确认本地结果，统计会在大数据后续定时扫描后更新。

## 7. 本服务调用外部接口的最小对接契约

### 7.1 产品批量上架

依据[产品服务 API](产品服务API.md)及用户确认，先查询供应商全部已上架产品，再仅对缺少的产品调用批量上架。以下两个路径均为产品服务路径，不使用本服务 /order/v2 前缀，不给查询路径追加 .do。当前只设计对接，不表示已经实现 Feign 或完成联调。

#### 7.1.1 查询已上架产品

`POST /third/erpQueryOnSaleProduct`，JSON 请求：

```json
{"supplierId":"example-real-supplier"}
```

| 请求字段 | 类型 | 来源/约束 |
| --- | --- | --- |
| supplierId | string | 必填，来自可信上下文的真实供应商 ID，联合销售主体也不传联合 ID |

响应为 `HttpResult<List<ErpOnSaleProductVo>>`。本次使用字段如下，每个字段单独列示；完整字段见产品服务 API 原文。

| 响应字段 | 类型 | 用途 |
| --- | --- | --- |
| success | boolean | 查询成功标识 |
| code | string | 按现有 HttpResult 成功码校验 |
| msg | string 或 null | 查询结果说明，异常信息脱敏后使用 |
| data | array | 供应商全部已上架产品，正常空集合必须为 [] |
| data[].productId | string | 产品 ID，命中产品后用于任务内复用 |
| data[].productName | string 或 null | 产品服务返回的名称，用作订单名称快照 |
| data[].supplierId | string | 必须与请求真实供应商一致 |
| data[].material | string | 材质代码，用于匹配导入产品 |
| data[].flutetype | number | 库内数字楞型编码，需通过字典与模板及上架接口的字母楞型对应 |
| data[].layer | number | 产品层数，用于匹配导入产品 |
| data[].productType | string 或 null | 产品类型；当前未将其增加为任务产品匹配键 |
| data[].marketingChannel | array 或 null | 销售渠道；当前不据此扩大“未上架”范围，也不改动已上架产品 |

文件完整暂存、基础结构检查通过后，在客户建档及产品上架前调用一次。按 `真实供应商 + material + 层数 + 规范楞型` 建只读产品索引；请求和响应供应商必须一致，不能只按材料名称或 productName 匹配。已有 `ProductFeign.getLayerList/getEdgeListByLayerId` 以及 `LayerModel/EdgeModel` 提供层数与楞型字典入口；返回数字 flutetype 与字典 edgeId 的实际对应关系须联调确认，不硬编码或按字符串直接比较数字和字母。无法转换或存在缺失业务键、无效产品 ID、同一业务键对应不同产品 ID 等歧义时，终结任务为 FAILED 并记录脱敏错误，避免误判为未上架后新增。

查询失败、超时、响应缺失或 data=null 时终结本地任务为 FAILED，errorMessage 提示已上架产品查询失败，不创建客户、产品或订单；不得将查询失败当成空列表。只有成功返回 data=[] 才表示没有已上架产品。该接口返回完整集合且没有分页参数，本服务不虚构分页；仅保留匹配所需字段，任务结束释放索引，供应商产品数量和响应体内存上线前压测。

每批合格订单先复用暂存表内已确认的产品处理结果，再匹配本次查询的已上架产品。命中时记录为复用，保存产品 ID 和返回名称，不调用上架接口，也不累计 productCreatedCount；未命中且本任务尚未处理的产品才进入上架请求。全量命中时不发送空的上架请求。后续批次继续复用首次结果，不重复查询供应商全集或重复上架。查询后其他系统仍可能新增产品，故保留上架接口 PRODUCT_EXISTS 分支处理该竞态。

#### 7.1.2 仅上架未命中产品

`POST /third/erpBatchAddProduct.do`，请求 body 是产品对象数组，仅包含未上架且本任务尚未处理的产品。

| 请求字段 | 来源/约束 |
| --- | --- |
| supplierId | 真实供应商 ID，不传联合 ID |
| supplierName | 真实供应商名称 |
| operatorId | 可信导入操作人 ID，不是模板业务员 ID |
| operator | 可信导入操作人姓名，不是模板业务员姓名 |
| material | 模板材料名称需确认为接口材质代码，不能仅凭列名认定语义一致 |
| flutetype | 模板楞型 |
| layer | 模板数字层数；接口文档仅支持 2～7 |
| productType | 后端默认传customized（定制产品），无需模板新增列或前端传参 |
| marketingChannel | 文档默认["offline"] |
| materialLengthPlus | 文档默认 0，落料长加值，不是订单落料长 |
| materialWidthPlus | 文档默认 0，落料宽加值，不是订单落料宽 |
| deliveryDay | 文档默认 2 |

请求未定义productName、idempotencyKey或taskId，不擅自增加这些参数。productName由产品服务生成；用户响应示例为MAT100/B，不能承诺原方案的“材料名称-层数楞型”。产品命名及相同材质/楞型不同层数的区分方式需对接确认。

每批订单先按真实供应商+material+layer+flutetype去重，排除已上架和本任务已有处理结果的产品后，再为本次实际提交的子集建立从 1 开始的 index 到产品自然键及依赖 Excel 行号的映射。index 不沿用过滤前的位置，不是 Excel 行号，也不保证与响应数组的位置相同。同一个产品的结果可影响多条订单，跨批复用任务内已确认结果；接口单次批量上限仍需确认，必要时将一批500行涉及的产品再拆小请求。

响应按用户约定处理：

- 顶层success=true、code="10001200"表示请求受理成功，不表示data内全部产品成功；必须逐条解析。
- 每条success=true、code=SUCCESS且productId非空，表示产品服务已成功入库并上架，依赖它的订单继续后续处理。成功产品不因同请求其他产品失败而撤销，不重发这些成功项。
- 逐项 code=PRODUCT_EXISTS 表示产品名称重复，按已有产品复用，相关订单继续处理，新增数不增加。该码可以随 success=false 返回，并允许缺少 productId。若返回 productName 则保存，缺少时保留空值。其他错误按实际 code 和脱敏 msg 记录。
- 校验 index 在本次请求 1～N 内且唯一。缺失、重复或越界时不能按数组位置猜测。新增成功的 SUCCESS 分支仍需有效 productId。
- productCreatedCount按本任务去重后已确认“新增成功”的产品数累加，不按依赖订单行数累加；不要求接口增加created/reused。

| 逐条code/示例 | 处理 |
| --- | --- |
| SUCCESS / 新增成功 | 确认productId后继续，新增数+1 |
| VALIDATE_ERROR / 材质代码不能为空、层数请输入指定参数 | 对应订单行失败，报告填写具体原因 |
| PRODUCT_EXISTS / 产品名称重复 | 对应订单继续，不计产品新增。该码优先于逐项 success=false 的通用失败处理 |
| SYSTEM_ERROR / 接单长宽参数错误 | 对应订单行失败；不能把所有SYSTEM_ERROR解释为名称重复 |
| AREA_MISSING / 该合作方未配置销售区域 | 对应订单行失败，提示配置问题，不伪造销售区域 |
| PARAM_NULL / 参数为空 | 对应订单行失败，同时排查本服务组装请求的问题 |

HTTP超时/断连、顶层失败或data为空时，不能认定整批未创建，也不能自动重发整批，避免成功项已经提交后重复上架。标记未确认结果，保留已成功档案/订单；需向产品服务查询核实。接口未声明幂等键，PRODUCT_EXISTS 仅作为已约定的单项复用结果。产品ID只用于本次流程确认/缓存，本地不新建产品档案表。

### 7.2 查询导入同步进度

大数据定时扫描 `crm_history_order`，处理已提交的新增和逻辑删除。导入记录分页为当前页符合条件的任务调用 `/ybill/import_order/statistics_progress`，拟复用 `DataServer` 的基址及 `appKey` 认证。同类接口使用 POST JSON，本接口的 HTTP 方法和参数位置仍待确认。

唯一业务入参为 `task_id`，取已通过归属校验的任务 ID。参数示例：

```json
{"task_id":"example-import-task"}
```

大数据返回示例：

```json
{
  "msg": "请求成功！",
  "code": "10001200",
  "data": [{"statistics_order_cnt": 1920}],
  "success": true
}
```

`statistics_order_cnt` 为该任务已统计订单数，含已取消订单（逻辑删除）。本服务校验 `success=true`、`code="10001200"`，并从唯一的结果项读取 `data[0].statistics_order_cnt`，映射到当前列表项的 `syncedCount`。正常返回数字 `0` 表示已统计 0 条。空数组、多条结果、缺少计数或计数超出 `[0, successCount]` 时按该任务进度不可用处理，保留本地记录及整页返回。一次请求只传一个 task_id，不假定返回批量任务计数。

扫描需按订单 `id` 幂等应用 `isdel` 变化，避免已删订单在大数据侧继续参与统计。具体扫描频率和增量策略由大数据决定。

### 7.3 查询供应商尺寸单位

依据[是否展示mm单位.md](是否展示mm单位.md)和用户确认，调用CRM的`POST /record/getShowUnitmm`。该路径为外部接口，不追加.do或本服务/order/v2前缀。

请求示例（占位ID）：

```json
{"supplierId":"example-real-supplier"}
```

虽然外部文档标记supplierId非必填，本服务必须从可信登录上下文显式填写真实供应商ID，联合销售主体不传联合ID。读取HttpResult的success和data.showUnitmm：

| 返回 | 本服务处理 |
| --- | --- |
| success=true且showUnitmm=true | mm，落料长宽只允许整数 |
| success=true且showUnitmm=false | cm，落料长宽最多1位小数 |
| 请求失败/超时、success不为true、data为空或showUnitmm为空 | UNIT_QUERY_FAILED，拒绝创建本次导入任务，不默认为cm |

同一任务仅在受理时查询一次，后续批次、未开始任务重新投递和报告重建均沿用已保存的单位。

## 8. 错误语义与前端处理

下列为拟新增HistoryOrderMsg的符号名；数字错误码实施时按项目注册分配，不把符号字符串直接冒充既有错误码。公共登录、校验和权限错误复用现有消息体系。

| 符号 | 语义/处理 |
| --- | --- |
| FILE_ALREADY_IMPORTED | 本公司相同fileUrl已有任务，提示重复导入，可返回原taskId |
| IMPORT_BUSY | 供应商提交锁竞争或同一真实供应商已有 QUEUED/RUNNING 任务；本次不创建任务，稍后重试，不泄露其他用户任务信息 |
| IMPORT_LOCK_UNAVAILABLE | Redis 分布式锁不可用或提交前失去锁；拒绝本次受理，不允许无锁创建任务 |
| UNIT_QUERY_FAILED / INVALID_FILE | 供应商单位查询失败或文件格式/地址不合法；单位查询失败时未创建任务，可用原文件地址重试 |
| TASK_NOT_FOUND / ORDER_NOT_FOUND | 不存在或超出对应接口可见范围；普通任务查询还需创建人为本人，不泄露真实归属 |
| INVALID_TASK_STATE | 目标订单的来源导入还未结束，暂不能删除 |
| REPORT_NOT_READY / REPORT_BUILD_FAILED / NO_ERROR_REPORT | 报告生成中/失败/无需报告 |
| TEMPLATE_UNAVAILABLE / DOWNLOAD_FAILED | 模板未配置或下载失败 |

行级失败通过报告和计数反馈。文件级错误由 errorMessage 展示。前端在导入记录列表中独立显示 localStatus、每条任务本次查询的 syncedCount 和报告可用状态。
