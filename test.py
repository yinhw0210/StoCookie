"""
PDD 登录测试脚本
用于排查 Playwright 自动化登录 PDD 被风控的问题。
运行: python test_pdd_login.py
"""
import asyncio
from playwright.async_api import async_playwright

PDD_LOGIN_URL = 'https://56-partner.pinduoduo.com/auth/login'
PDD_TARGET_URL = 'https://56-partner.pinduoduo.com/delivery-workbench/order'
ACCOUNT = '17753992087'
PASSWORD = 'TTrr1234'


async def main():
    async with async_playwright() as p:
        # 使用系统已安装的 Chrome/Edge，而非 Playwright 内置 Chromium
        # 这样浏览器版本、指纹和你正常使用的完全一致
        print('[1] 尝试使用系统 Chrome/Edge 启动...')
        try:
            browser = await p.chromium.launch(
                headless=False,
                channel='msedge',  # 使用系统 Edge；如果没有 Edge 改为 'chrome'
            )
            print('[1] 成功使用系统 Edge 启动')
        except Exception as e:
            print(f'[1] Edge 启动失败: {e}，尝试 Chrome...')
            try:
                browser = await p.chromium.launch(
                    headless=False,
                    channel='chrome',
                )
                print('[1] 成功使用系统 Chrome 启动')
            except Exception as e2:
                print(f'[1] Chrome 也失败: {e2}，使用 Playwright 内置 Chromium')
                browser = await p.chromium.launch(headless=False)

        context = await browser.new_context()
        page = await context.new_page()

        # 打印实际的 UA 和 sec-ch-ua
        ua = await page.evaluate('navigator.userAgent')
        print(f'[2] User-Agent: {ua}')
        try:
            ua_data = await page.evaluate('''() => {
                if (navigator.userAgentData) {
                    return JSON.stringify(navigator.userAgentData.brands);
                }
                return "userAgentData not available";
            }''')
            print(f'[2] sec-ch-ua brands: {ua_data}')
        except Exception:
            pass

        # 导航到登录页
        print(f'[3] 导航到登录页: {PDD_LOGIN_URL}')
        await page.goto(PDD_LOGIN_URL, wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(3000)
        print(f'[3] 当前 URL: {page.url}')

        # 填写表单
        print('[4] 填写账号密码...')
        account_input = page.locator('#account')
        password_input = page.locator('#password')
        submit_btn = page.locator('button[type="submit"]')

        await account_input.fill(ACCOUNT)
        await page.wait_for_timeout(500)
        await password_input.fill(PASSWORD)
        await page.wait_for_timeout(1000)

        # 监听登录请求的响应
        print('[5] 提交登录，监听 API 响应...')

        async def handle_response(response):
            if 'user/login' in response.url:
                try:
                    body = await response.json()
                    print(f'[API] {response.url}')
                    print(f'[API] Status: {response.status}')
                    print(f'[API] Response: {body}')
                except Exception:
                    print(f'[API] {response.url} -> Status: {response.status} (无法解析 body)')

        page.on('response', handle_response)

        await submit_btn.click()
        print('[5] 已点击登录按钮，等待响应...')

        # 等待结果
        await page.wait_for_timeout(10000)
        print(f'[6] 登录后 URL: {page.url}')

        if '/auth/login' in page.url:
            print('[结果] 登录失败，仍在登录页')
            # 截图保存
            await page.screenshot(path='pdd_login_failed.png')
            print('[结果] 已截图: pdd_login_failed.png')
        else:
            print('[结果] 登录成功！已跳转')
            # 导航到目标页
            await page.goto(PDD_TARGET_URL, wait_until='domcontentloaded', timeout=20000)
            await page.wait_for_timeout(3000)
            print(f'[结果] 目标页 URL: {page.url}')

            # 检查 cookie
            cookies = await context.cookies()
            pdd_cookies = [c for c in cookies if '56-partner' in c.get('domain', '')]
            print(f'[结果] PDD 域名下 cookie 数: {len(pdd_cookies)}')
            for c in pdd_cookies:
                print(f'  {c["name"]} @ {c["domain"]}')

        print('\n[完成] 浏览器保持打开，按 Ctrl+C 退出')
        # 保持浏览器打开方便观察
        try:
            await asyncio.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
