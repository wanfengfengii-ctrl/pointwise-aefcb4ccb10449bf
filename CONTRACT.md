# 校准值索引交接约定

## 当前可运行材料
Python标准库与SQLite足够，无下载或外部服务。legacy.py是完整旧实现及语义参照；warehouse.py当前直接导出它的Store。storage2.py是已能工作的目标存储口，不是待实现的SDK。保留legacy.py、storage2.py及checks.py已有断言；可增加验证。

在仓库根目录执行：
- python3 checks.py normal：创建内存旧库，执行完整两批样本、回执重放、范围分页、冲突回滚和撤销复活。
- python3 checks.py demo：输出旧库完整状态及实际范围页。
- python3 storage2.py：核对目标存储口实际BLOB范围查询。
- python3 seed.py old.db：按samples.json逐批调用旧接口，创建可交付升级的真实SQLite旧库并打印状态。重复调用只重放已有请求。

.pointwise-runtime.json是当前运行清单。交付时verify必须实际核对从seed.py同样方式生成的旧库升级、重新打开后的旧接口及新存储，demo必须展示真实升级前后范围页，不能只有编码单测或成功文字。可自行选择新增验证入口；不规定测试数量。

## 旧格式和入口
legacy.Store(path)打开或创建格式1数据库。warehouse.Store(path)是业务入口，升级完成后仍从此入口使用。close关闭连接。现有数据、DDL、所有可调用参数及返回字段均由legacy.py完整定义；以下明确有意保留的细节。

meta只有一行(format,generation)，初始(1,0)。
entries(raw TEXT COLLATE KEY1 PRIMARY KEY,rev INTEGER NOT NULL,value TEXT NOT NULL,deleted INTEGER NOT NULL)，raw/value为legacy.dump生成的JSON文本。
receipts(request TEXT PRIMARY KEY,payload TEXT NOT NULL,result TEXT NOT NULL)，payload保存原请求rows的完整规范JSON，不对其中键写法做约分或大小写归一。result保存首次回执JSON。

key是0至8项的列表，[]也是合法键。每项恰为以下一种：
- ["z"]：空值。
- ["n",p,q]：p/q；p、q为可带正负号与前导零的ASCII整数字符串；q非零，abs(int(p))、abs(int(q))各至多4096比特。不允许小数点、空白。分母可为负。比较按精确有理数，零和等价分数为同一逻辑键。
- ["s",text]：无代理码点的Unicode字符串，按Python字符串码点顺序；允许空串、NUL及非BMP字符，不作Unicode归一化。
- ["b",hex]：长度为偶数的十六进制字符串，大小写不限，无空格；按对应原始字节顺序，允许空字节串。

类型次序为空值<数<文本<字节；同类型比较值。复合键逐项字典序，真前缀排在长键之前。无边界用None，不能用[]代替。legacy.normalize/compare/canonical给出完整参照；canonical约分、分母转正、数字转标准十进制，字节转小写hex，其余不变。

apply(request,rows)的rows每项字段恰为key、rev、value、deleted。rev为正整数且不接受bool；deleted为bool；删除时value为None，否则value为JSON对象。JSON值仅限标准JSON，拒绝NaN/Infinity。批内同一逻辑键只能出现一次。非法键、非法行及重复键在事务之前校验，其异常沿用参照。

每逻辑键只保存最高修订，低修订忽略；同修订相同value/deleted是空操作，即使key写法不同；同修订异内容报REVISION_CONFLICT并整批回滚。高修订写入保留此次原始键写法，删除也是一条持久墓碑，可被更高修订复活。相同request和相同payload返回首次回执，优先于当前修订判断；同request异payload报REQUEST_CONFLICT。等价分数的不同写法仍是不同请求payload，不能归一化回执绑定。每次新请求成功使generation加一，即使rows为空或accepted为0；重放不加一。所有行、代次、回执原子提交。

snapshot()返回generation、全部行（含墓碑）、receipts；行按逻辑键排序，receipts按request排序，三个字段均须与参照一致，原始键及payload字符串也须一致。scan(lower=None,upper=None,after=None,limit=20)返回generation、未删除rows、after。lower闭、upper开、after严格大于；多个边界同时成立才入选，limit为正整数。after为本页最后一行的原始key，没有行则为None；它是可序列化的逻辑边界，不绑定某条现存记录或数据库行号。传入被删键、未出现过的等价写法或前缀均按同一规则。每次调用自身读取同一SQLite快照，不要求跨页固定历史快照。

样本依次执行load、revise后generation=2，9条状态行、8条可见行。范围lower=[["n","1","3"]]、upper=[["s","A"]]、limit=2得到amount为25、22的两行，after=[["n","1","3"],["s",""]]。用此after继续得到31、30、-40。load首次回执始终为{"generation":1,"accepted":9}。checks.py保留了这些可观察断言。

## 新格式与编码边界
新增keycodec.pack(key)->bytes及keycodec.unpack(blob)->canonical_key。unpack只要求处理pack产生的字节，不要求开发通用损坏文件解码器。pack必须为无I/O纯函数，不依赖数据库、调用次序、全局业务键集或预计算排序表。非法key沿用legacy.normalize的KEY异常。对任意合法a、b：
- unpack(pack(a)) == legacy.canonical(a)。
- pack(a) == pack(b)当且仅当compare(a,b)==0。
- bytes的原生字典序比较结果必须与legacy.compare完全相同；也必须与SQLite BLOB比较次序一致。

令B初值为1，每个键项先加1，再按类型增加：数加规范分子绝对值的bit_length与规范正分母的bit_length；文本加UTF-8字节数；字节加原始字节数；空值不再增加。len(pack(key))不得超过32+8*B。该界排除按分子数值、分母数值或二者商值逐次重复的编码，也排除固定精度离散化。原始数字写法有多少前导零不增加B。不得使用float、Decimal舍入、固定分母公共网格或有损哈希决定次序。须说明编码的顺序、唯一性、终止边界及长度界为何成立。

格式2保留meta与receipts的原始内容，只将meta.format设为2。业务行使用storage2.DDL的entries2，k为pack(raw所表示的逻辑键)，其余四列逐字保留旧内容。旧entries在同一切换事务中移除，不保留旧排序索引或逻辑键到秩的辅助表。格式2打开、写入、snapshot与scan均不得注册或调用自定义SQLite比较器；范围查询必须调用未改动的storage2.range_rows，边界先独立编码成bytes，让SQL直接完成约束、排序和LIMIT。snapshot允许读取全部状态；scan不能先读全表或全部键再筛选排序，不能额外维护逻辑排序索引。可以复用旧的输入校验和回执函数，但不能回到旧entries处理业务。

新增migration.upgrade(path)->{"format":2,"rows":N}，N为含墓碑的状态行数。只需对已有合法格式1库及格式2库工作，不负责从无文件路径初始化。维护人员保证升级期间没有其他写入者，不要求在线追日志、分批推进或并行升级。完整编码、目标建表、原始行与回执保留、删旧表及格式切换必须共同提交；转换或写入异常须回滚并关闭内部连接。进程中断后重新打开只能见完整格式1或完整格式2。对格式2重复upgrade返回同一形状、当前状态行数，不改变行、generation或receipts。

warehouse.Store须继续打开格式1和格式2；仅显式upgrade才能改变已有格式1库。新建库默认可任选格式1或2。使用格式2时不能依赖KEY1的注册，关闭后用仅sqlite3.connect建立的连接也须能读到按k排序的目标行。升级前产生的scan.after可直接传给升级后的Store.scan。升级后的apply须立即进入entries2，raw写法保留与逻辑键规范身份分离；关闭重开后新写、墓碑复活与历史请求重放均继续满足旧契约。

交付说明须写明编码规则与格式识别、原子切换边界，以及如何重跑真实旧库升级及失败回滚验证。本题不要求历史快照、并发迁移、网络服务或通用命令行产品。
