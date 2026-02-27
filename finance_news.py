import requests
import time
from bs4 import BeautifulSoup
import random
from datetime import datetime, timedelta
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
GLM_API_KEY = os.environ.get("GLM_API_KEY")
EMAIL_PASSWORD = os.environ.get("QQ_EMAIL_AUTH_CODE")
EMAIL_FROM = os.environ.get("EMAIL_FROM")
EMAIL_TO = os.environ.get("EMAIL_TO")

# ================== 基本配置 ==================

# 东方财富财经新闻页面
# 需要抓取的多个页面
FINANCE_URLS = [
    "https://finance.eastmoney.com/a/czqyw.html",  # 证券要闻
    "https://www.cnstock.com/channel/10233",       # 上海证券报A股
]

# 强化请求头，模拟国内浏览器
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://www.eastmoney.com/",  # 来源页
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

# 在 GitHub Actions 中保存日志的目录（相对当前工作目录）
SAVE_PATH = "./logs/"

# 智谱 GLM 配置（推荐从环境变量/Secrets 中读取）
# - 本地：可以放在 .env 里
# - GitHub Actions：放在仓库 Settings -> Secrets -> Actions
GLM_API_KEY = os.environ.get("GLM_API_KEY")
GLM_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
GLM_MODEL = "glm-4-flash"

# 邮件配置（QQ 邮箱）
sender_name = "财经资讯助手"   # 发件人名称
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 587
EMAIL_FROM = "439472808@qq.com"   # 发件人邮箱（QQ 邮箱）
EMAIL_TO = "439472808@qq.com"     # 收件人邮箱，可以和发件人一样
# 授权码从环境变量/Secrets 中读取
EMAIL_PASSWORD = os.environ.get("QQ_EMAIL_AUTH_CODE")


# ================== 抓取东方财富新闻 ==================

def fetch_finance_news():
    target_urls = [
        "https://finance.eastmoney.com/a/czqyw.html",
        "https://finance.eastmoney.com/a/cgspl.html",
        "https://finance.eastmoney.com/"
    ]
    all_news = []
    
    for url in target_urls:
        print(f"正在抓取：{url}")
        try:
            # 随机延迟（避免高频请求）
            time.sleep(random.uniform(3, 5))
            # 发起请求，允许重定向
            response = requests.get(
                url, 
                headers=HEADERS,
                timeout=15,
                allow_redirects=True,
                verify=False  # 跳过SSL验证（境外节点可能证书问题）
            )
            # 新增调试日志（关键！看返回内容）
            print(f"URL: {url} | 状态码: {response.status_code}")
            print(f"网页内容长度: {len(response.text)} 字符")
            print(f"前200字符内容: {response.text[:200]}")  # 看返回的是不是有效内容
            
            if response.status_code == 200 and len(response.text) > 1000:
                response.encoding = "utf-8"
                soup = BeautifulSoup(response.text, "html.parser")
                # 重新确认东方财富网的新闻标签（避免选择器失效）
                # 替换成更通用的选择器（东方财富网新闻列表的通用标签）
                news_items = soup.find_all("div", attrs={"class": lambda x: x and "news-item" in x})
                print(f"当前URL解析到 {len(news_items)} 条新闻")
                all_news.extend(news_items)
            else:
                print(f"URL: {url} 返回无效内容，跳过")
        except Exception as e:
            print(f"抓取 {url} 失败：{str(e)}")
            continue
    
    # 去重+提取核心信息
    unique_news = []
    seen_titles = set()
    for item in all_news:
        # 提取标题（兼容不同标签）
        title_tag = item.find("a") or item.find("h3")
        title = title_tag.get_text(strip=True) if title_tag else ""
        if title and title not in seen_titles:
            seen_titles.add(title)
            unique_news.append({"标题": title})
    
    print(f"共抓取到 {len(unique_news)} 条新闻（去重后）")
    return unique_news

# ================== 用 GLM 进行要点整理 ==================

def build_glm_prompt(news_list):
    """
    把抓取到的多条新闻，整理成一个 Prompt 给 GLM。
    要求 GLM 输出：逐条要点 + 全局总结。
    """
    beijing_time = datetime.utcnow() + timedelta(hours=8)
    date_str = beijing_time.strftime("%Y-%m-%d")

    prompt = f"今天是 {date_str}。以下是从东方财富财经频道抓取的新闻，请你：\n" \
             f"1）逐条用简明要点（1-3 句）概括每条新闻对投资者的核心影响；\n" \
             f"2）最后给出一个总体市场环境/政策风向的小结（3-5 句）；\n" \
             f"3）整体输出为中文，编号清晰。\n\n"

    prompt += "以下是原始新闻列表：\n"
    for i, news in enumerate(news_list, 1):
        prompt += (
            f"{i}. 标题：{news['标题']}\n"
            f"   发布时间：{news['发布时间']}\n"
            f"   摘要：{news['摘要']}\n"
            f"   链接：{news['链接']}\n\n"
        )
    return prompt


def summarize_with_glm(news_list):
    if not news_list:
        return "今日暂无可用的财经资讯，或抓取失败。"

    if not GLM_API_KEY:
        # 没配置 API Key 时的兜底
        return "未配置 GLM_API_KEY 环境变量，无法调用智谱大模型，请先在 PythonAnywhere 配置。"

    prompt = build_glm_prompt(news_list)

    try:
        headers = {
            "Authorization": f"Bearer {GLM_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": GLM_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.3
        }
        resp = requests.post(GLM_API_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content
    except Exception as e:
        print(f"调用 GLM 失败：{e}")
        return "调用智谱 GLM 接口失败，请检查网络、API Key 或配额。"


# ================== 保存到文件（可选） ==================

def save_summary_to_file(summary_text):
    if not os.path.exists(SAVE_PATH):
        os.makedirs(SAVE_PATH, exist_ok=True)

    beijing_time = datetime.utcnow() + timedelta(hours=8)
    filename = os.path.join(SAVE_PATH, f"财经资讯总结_{beijing_time.strftime('%Y%m%d_%H')}.txt")
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(summary_text)
        print(f"总结已保存到：{filename}")
    except Exception as e:
        print(f"保存失败：{e}")


# ================== 发送 QQ 邮件 ==================

def send_email(subject, body):
    if not EMAIL_PASSWORD:
        print("未配置 QQ_EMAIL_AUTH_CODE 环境变量，无法发送邮件。")
        return

    message = MIMEText(body, "plain", "utf-8")
    message["From"] = Header(EMAIL_FROM, "utf-8")
    message["To"] = Header(EMAIL_TO, "utf-8")
    message["Subject"] = Header(subject, "utf-8")

    try:
        import ssl
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, [EMAIL_TO], message.as_string())
        print("邮件发送成功。")
    except Exception as e:
        print(f"邮件发送失败：{e}")


# ================== 主任务：抓取 + 总结 + 发邮件 ==================

def daily_finance_task():
    beijing_time = datetime.utcnow() + timedelta(hours=8)
    print(f"\n开始执行 {beijing_time.strftime('%Y-%m-%d %H:%M:%S')} 财经资讯任务...")

    news = fetch_finance_news()
    print(f"共抓取到 {len(news)} 条新闻。")

    glm_summary = summarize_with_glm(news)

    # 邮件主题和正文
    subject = f"{beijing_time.strftime('%Y-%m-%d %H:00')} 东方财富财经资讯要点整理"
    body = glm_summary

    print("=" * 50)
    print(body)
    print("=" * 50)

    # 保存到文件（可选）
    save_summary_to_file(body)

    # 发送到 QQ 邮箱
    send_email(subject, body)


if __name__ == "__main__":
    daily_finance_task()
