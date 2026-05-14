const LOGIN_URL = 'https://tv.hohai.eu.org/api/auth/login';
const CHECKIN_STATUS_URL = 'https://tv.hohai.eu.org/api/checkin/status';
const CHECKIN_URL = 'https://tv.hohai.eu.org/api/checkin';

function nowCN() {
  return new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' }).replace(' ', 'T') + '+08:00';
}

function safeJson(res) {
  return res.text().then((t) => {
    try {
      return JSON.parse(t);
    } catch {
      return { raw: t };
    }
  });
}

function iconBySuccess(ok) {
  return ok ? '🟢' : '🔴';
}

async function sendTelegram(env, payload) {
  const token = env.HOHAI_TGTK;
  const chatId = env.HOHAI_TGID;
  if (!token || !chatId) return;

  const text = [
    `${iconBySuccess(payload.signed_today)} Hohai 自动签到通知(Workers)`,
    `📌 状态：${payload.status}`,
    `🗓️ 今日是否已签到：${payload.signed_today ? '是' : '否'}`,
    `💰 账户余额：${payload.balance || '未识别'}`,
    `📝 备注：${payload.note || '无'}`,
    `⏰ 时间：${payload.time}`,
  ].join('\n');

  await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text, disable_web_page_preview: true }),
  });
}

async function doCheckin(env) {
  const username = env.HOHAI_UN;
  const password = env.HOHAI_PW;
  if (!username || !password) {
    return {
      time: nowCN(),
      status: '执行失败',
      signed_today: false,
      balance: null,
      note: '缺少 HOHAI_UN 或 HOHAI_PW',
    };
  }

  const result = {
    time: nowCN(),
    status: '执行失败',
    signed_today: false,
    balance: null,
    note: '',
  };

  try {
    const loginRes = await fetch(LOGIN_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userName: username, password }),
    });
    const loginBody = await safeJson(loginRes);

    if (!loginRes.ok || (loginBody && loginBody.success === false)) {
      result.note = `登录失败: HTTP ${loginRes.status} ${JSON.stringify(loginBody).slice(0, 300)}`;
      return result;
    }

    const token =
      loginBody?.token ||
      loginBody?.data?.token ||
      loginBody?.data?.accessToken ||
      loginBody?.accessToken ||
      null;

    const headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = `Bearer ${token}`;

    const statusRes = await fetch(CHECKIN_STATUS_URL, { method: 'GET', headers });
    const statusBody = await safeJson(statusRes);

    const alreadySigned =
      statusBody?.data?.checkedIn === true ||
      statusBody?.data?.isCheckedIn === true ||
      statusBody?.checkedIn === true ||
      statusBody?.isCheckedIn === true ||
      /已签到|already/i.test(JSON.stringify(statusBody));

    if (alreadySigned) {
      result.status = '今日已签到';
      result.signed_today = true;
      result.note = '状态接口显示今日已签到';
      result.balance = statusBody?.data?.balance ?? statusBody?.balance ?? null;
      return result;
    }

    const checkinRes = await fetch(CHECKIN_URL, { method: 'POST', headers, body: JSON.stringify({}) });
    const checkinBody = await safeJson(checkinRes);

    const success =
      checkinRes.ok &&
      (checkinBody?.success === true || checkinBody?.code === 0 || /成功|success/i.test(JSON.stringify(checkinBody)));

    if (success) {
      result.status = '本次签到成功';
      result.signed_today = true;
      result.note = '调用 /api/checkin 成功';
      result.balance = checkinBody?.data?.balance ?? checkinBody?.balance ?? null;
    } else {
      result.status = '签到失败';
      result.note = `签到接口返回异常: HTTP ${checkinRes.status} ${JSON.stringify(checkinBody).slice(0, 300)}`;
      result.balance = checkinBody?.data?.balance ?? checkinBody?.balance ?? null;
    }

    return result;
  } catch (e) {
    result.status = '执行失败';
    result.note = String(e?.message || e);
    return result;
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/run') {
      const result = await doCheckin(env);
      await sendTelegram(env, result);
      return new Response(JSON.stringify(result, null, 2), {
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        status: result.signed_today ? 200 : 500,
      });
    }
    return new Response('OK. Use /run', { status: 200 });
  },

  async scheduled(_event, env, _ctx) {
    const result = await doCheckin(env);
    await sendTelegram(env, result);
  },
};
