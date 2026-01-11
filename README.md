# 活着呢 


这是一个简单、轻量的每日签到 Web 应用，专为局域网或个人服务器部署设计。它支持多用户管理、微信/邮件通知提醒，以及长时间未签到自动清理功能。
<img width="28" height="28" alt="非常满意" src="https://github.com/user-attachments/assets/2b949fae-4de6-4c63-9465-e80d6663f2a6" />
项目名称：**活着呢**

## 主要功能
- 连续签到天数统计
- 微信通知和邮件通知
- 支持多邮箱 多个企业微信链接通知
- 自动清理长期未活跃用户数据

## 部署方式

### 1. 环境准备
确保您的电脑上已安装 Python 3 环境。

### 2. 安装依赖
在终端中进入项目目录，运行以下命令安装所需依赖：
```bash
pip install -r requirements.txt
```

### 3. 配置环境变量
项目使用 `.env` 文件来存储敏感配置（如邮箱账户信息）。
您需要编辑项目根目录下的 `.env` 文件。

**开发者只要替换成自己的邮箱配置即可：**

```ini
MAIL_USERNAME=your_email@qq.com
MAIL_PASSWORD=your_auth_code     # 邮箱授权码
MAIL_SERVER=smtp.qq.com          # 发送邮件服务器
MAIL_PORT=465                    # 端口号
```

*注：`/Users/suntianyu/Desktop/未命名文件夹 5/.env` 即为该配置文件。*

### 4. 启动项目
在终端中运行：
```bash
python3 app.py
```

启动后，控制台会显示访问地址（例如 `http://192.168.1.x:5001`）。请确保手机和电脑连接在同一局域网下，在手机浏览器中输入该地址即可访问。
