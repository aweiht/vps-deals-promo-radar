::ILANG
[TYPE:instructions][PROJECT:vps-deals-promo-radar][LANG:zh]

::STATE{@PROJECT, purpose:为英语用户提供可溯源的官方 VPS 优惠与价格对比, owner:user}
::MODULE{STACK|title:技术栈}
  Python 3.11+ 标准库；静态 HTML/CSS；无运行时推理、第三方 Python 包、手工 API 密钥或付费服务。
::MODULE{LAYOUT|title:目录与命名}
  .ilang/ 存放唯一站点配置 site.ilang；templates/ 存放 HTML 模板；assets/ 存放品牌样式与图片。
  data/ 存放抓取结果和来源状态；tests/ 存放确定性验证与最小来源样例；site/ 为生成输出。
  evidence/ 存放本地验收证据，不提交；英文文件名使用 snake_case 或 kebab-case。
  生成文件可在限定输出目录内覆写；清理和删除须取得明确授权，不自动清理其他目录。
::MODULE{START|title:启动}
  python3 scraper.py
  python3 build.py
  python3 -m http.server 8765 --directory site
  python3 -m unittest discover -s tests
::MODULE{DEPLOY|title:部署}
  目标为 Cloudflare Pages，构建命令 python build.py，输出目录 site，生产分支 main；当前状态见 README.md。
  GitHub Actions 每 6 小时运行标准 Linux runner，使用平台临时 GITHUB_TOKEN 提交数据；不保存长期密钥。
::MODULE{AUTHORIZATION|title:本次已授权范围}
  用户已批准创建公开 GitHub 仓库、提交及 push 本项目、配置 6 小时更新管线、连接 Cloudflare Pages 并上线。
  允许在本项目内实现、修复、真实公开来源抓取、测试及合理重试；不拓展到其他项目或账号。
::RULE{scraper.py 与 build.py 必须读取 .ilang/site.ilang；不得另存硬编码厂商清单}
::RULE{只抓公开官方入口并遵守 robots.txt；每主机低并发、有超时、有请求上限；被拦截即停止该来源}
::RULE{每条价格必须保留计费周期与证据；没有价格或日期就不写相应字段；不推断优惠、库存、佣金或到期日}
::RULE{失败隔离到厂商；最后成功结果可保留但必须明确陈旧或过期；全失败必须报告失败}
::RULE{输出 HTML 转义外部数据；仅允许 HTTPS 官方链接与已获批准的联盟链接}
::RULE{所有 Python 文件头部包含 3 至 5 行 I-Lang 职责与边界说明}
::RULE{维护 README.md 的当前状态、授权、真实验收和下一步；历史结果不代表当前线上状态}
::BOUNDARY{never:编优惠 编价格 编佣金 绕反爬 抓登录数据 外发私有数据 刷量 自动发社交消息 购买域名或付费服务|scope:permanent}
::BOUNDARY{requires_explicit_approval:新增费用 新供应商 敏感配置 删除文件 改写历史 超出本次范围的发布或系统变更}
