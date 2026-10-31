# tailscale自建服务器后台

基于 **Headscale 0.29.6** 的中文管理后台，提供设备、用户组、接入密钥和客户端互访管理。前端为原生 HTML/CSS/JavaScript，后端仅使用 Python 标准库，通过本机 Headscale CLI 管理数据。

这是独立的管理界面，不是 Tailscale 官方控制台，也不包含 Headscale、DERP 或 Tailscale 客户端安装器。需要先部署可用的 Headscale 服务。

## 功能

- 紧凑统计卡片和设备表格；支持按名称、在线状态、用户组、IP、最近在线时间排序。
- 设备状态每 15 秒刷新，保留当前排序。
- 中文后台备注、客户端 DNS 名称编辑、复制地址、打开设备管理页、注销与移除设备。
- 用户组设备详情；按组控制普通客户端互访。
- 接入密钥生成、重复使用、临时设备、主动失效；可选长期有效密钥。
- 同组路由器重刷后的注册历史归并及原备注继承。
- 管理密码修改、HTTPS 安全会话、CSRF 与 Origin 校验。

## 环境

- Linux + systemd；Python 3.10 或更新版本，无需 pip 运行依赖。
- **已验证 Headscale 0.29.6**，默认二进制 `/usr/local/bin/headscale`，配置 `/etc/headscale/config.yaml`。
- Headscale 使用 SQLite，默认 `/var/lib/headscale/db.sqlite`。
- Headscale 配置 `policy.mode: database`，供用户组互访开关动态更新策略。
- 服务用户 `headscale` 需能读取 Headscale 配置并通过 CLI 访问服务，按可选功能访问数据库。
- Caddy 或现有反向代理提供可信 HTTPS。Python 服务只监听 `127.0.0.1:18444`。

其他 Headscale 版本、PostgreSQL 和不同 CLI 输出尚未验证；不要直接视为兼容。

## 安装

```sh
git clone https://github.com/TangSengVIP/tailscale-selfhosted-admin.git
cd tailscale-selfhosted-admin
sudo sh scripts/install.sh
sudo editor /etc/headscale-admin/admin.env
sudo python3 scripts/create_admin.py --username your-admin-name
sudo chown headscale:headscale /etc/headscale-admin/auth.json
```

密码通过终端交互输入，不提供默认账号或密码。安装器保留已有配置和密码文件，不会自动启动服务、改写 Headscale 配置或覆盖反向代理。

参照 [配置示例](deploy/admin.env.example) 设置：

- `AUROSA_ADMIN_ORIGIN`：管理后台浏览器的 origin，例如 `https://admin.example.com`，不包含路径或结尾 `/`。
- `HEADSCALE_URL`：Tailscale 客户端连接的控制服务器，例如 `https://headscale.example.com`。
- `AUROSA_ADMIN_COOKIE_PATH`：独立域名用 `/`；部署到子路径时与该路径一致，例如 `/admin/`。
- `HEADSCALE_BIN`、`HEADSCALE_CONFIG`、`HEADSCALE_DB`：实际安装位置。
- `AUROSA_ADMIN_GROUP`：管理员设备的展示分组名称，默认 `admin`。实际访问权限由 ACL 标签决定。

配置反向代理后启动：

```sh
sudo systemctl enable --now headscale-admin
sudo systemctl status headscale-admin
sudo journalctl -u headscale-admin -n 50 --no-pager
```

[Caddy 示例](deploy/Caddyfile.example) 支持独立管理域名或现有控制域名下的 `/admin/`。子路径代理必须去掉前缀，访问地址必须以 `/` 结尾。控制服务器的现有代理保留不变。后台与控制服务器可以使用不同域名。

## 访问策略与管理员设备

[策略示例](deploy/policy.example.hujson) 允许 `tag:aurosa-admin` 主动访问全部设备，普通设备默认无互访规则。现有环境应先备份并合并现有策略，不要直接覆盖。

确认 Headscale 已切换到数据库策略模式后，可使用 CLI 导入已审核的策略：

```sh
headscale -c /etc/headscale/config.yaml policy set --file=/path/to/reviewed-policy.hujson
```

用户组开关添加或移除该用户对应的自访 ACL；不会删除其他规则。**现有宽泛 allow-all 规则仍会生效**，开关不能撤销其他规则授予的访问权限。

管理员访问能力来自 `tag:aurosa-admin` 标签，不是显示名称或用户组名称。`tagOwners` 的空列表禁止普通用户自行申请管理员标签；应由可信管理员通过服务端配置标签。示例策略不允许普通设备主动访问管理员，已建立连接的响应流量不受此描述限制。

## 重刷固件与名称继承

重刷清除了 Tailscale 状态时，会注册新身份，远程 IP 可能改变。后台按**同用户组 + 完整原始主机名**归并指定格式的路由器注册历史：

- 支持 `AurosaRouter-` 或 `TitsLeeRouter-` 加 6–12 位十六进制硬件后缀。
- 最新记录显示在主列表；新记录没有独立备注时继承旧备注。
- 旧记录可通过“注册历史”查看；不从 Headscale 自动删除。
- 旧身份仍在线时不归并；管理员或带标签设备不自动归并。

这只是展示层关联，**主机名可由客户端声明，不是可信硬件凭据**。不依据主机名转移权限、身份密钥或 IP。历史备注保留在 `device-names.json` 中；备份时应同时保存该文件。客户端 DNS 名称不会因此自动恢复成旧名称。

## 长期有效密钥

Headscale 0.29.6 的数据库模型支持 NULL 到期时间，但其 CLI 会产生有限到期时间。此后台的可选兼容实现先创建新密钥，再以 SQLite 事务将该条新记录的到期时间设为 NULL，并检查用户、前缀、标签和使用状态；失败时删除新生成的密钥。

默认关闭该功能。只有确认使用 **0.29.6 + SQLite**、已备份数据库后，才将环境文件中的 `HEADSCALE_ALLOW_DB_KEYS=1` 并重启后台。未启用时选择“长期有效”会返回明确错误，不会创建密钥。升级 Headscale 前应重新验证此实现。

长期有效不代表不可撤销，可以在后台使密钥失效。完整密钥只在创建结果中显示；本仓库不提供任何实际接入密钥。

## 文件结构

```text
src/                     Python 服务与网页资源
scripts/create_admin.py  交互创建密码哈希
scripts/install.sh       安装到现有 Headscale 主机
deploy/                  systemd、环境、Caddy 和策略示例
tests/                   注册历史与认证/HTTP 回归测试
.github/workflows/       基础 CI 检查
```

## 开发与验证

```sh
python -m compileall -q src scripts tests
python -m unittest discover -s tests -v
node --check src/app.js
node tests/frontend.cjs
sh -n scripts/install.sh
```

后端无需第三方依赖；Node.js 仅用于前端语法与排序回归验证。测试不连接真实 Headscale，不注册或删除实际设备。CI 使用 Ubuntu、Python 3.12 和 Node.js 22。

## 维护与备份

- 更新源码后重新执行安装脚本，再 `systemctl restart headscale-admin`。已有密码与环境文件会保留。
- 备份 `/etc/headscale-admin/` 和 Headscale 自身数据库/配置；其中包含敏感资料，勿上传公开仓库。
- 本仓库只含通用源码与示例，不含部署凭据、生产设备记录、固件接入密钥或私人服务器配置。
- 后台管理权限等同于高权限 Headscale 管理能力，应仅供可信管理员使用。
