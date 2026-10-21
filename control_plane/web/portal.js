'use strict';
// Intentionally no storage, URL credentials, third-party scripts or raw HTML insertion.
let licenseKey = '';
let busy = false;
let generation = 0;
const $ = id => document.getElementById(id);
const message = text => { $('message').textContent = text; };

async function api(path, method = 'GET', body) {
  const currentKey = licenseKey;
  const response = await fetch(path, {
    method,
    headers: { Authorization: `Bearer ${currentKey}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    credentials: 'omit',
    cache: 'no-store',
    redirect: 'error',
  });
  if (!response.ok) {
    const errors = { 401: 'Your credential is invalid, expired or revoked. Ask your administrator for a current key.', 404: 'This device is not available in your workspace.', 409: 'All device seats are occupied. Revoke an old device or ask your administrator for another seat.', 422: 'Check the supplied fields and try again.', 429: 'Too many requests. Wait one minute before trying again.' };
    throw new Error(errors[response.status] || 'The metadata service is unavailable. Try again later.');
  }
  return response.json();
}

function appendText(parent, tag, value, className) {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  parent.append(node);
  return node;
}

function hideCredential() {
  $('device-key').textContent = '';
  $('device-id').textContent = '';
  $('new-credential').hidden = true;
}

function signOut() {
  generation += 1;
  licenseKey = '';
  $('license-key').value = '';
  $('login-panel').hidden = false;
  $('workspace').hidden = true;
  for (const id of ['license-info', 'devices', 'performance']) $(id).replaceChildren();
  $('customer-name').textContent = 'Your license';
  hideCredential();
  message('Signed out.');
}

async function refresh() {
  const current = generation;
  const [me, devices, performance] = await Promise.all([api('/v1/customer/me'), api('/v1/customer/devices'), api('/v1/customer/performance')]);
  if (current !== generation || !licenseKey) return;
  $('customer-name').textContent = me.customer.name;
  $('license-info').replaceChildren();
  for (const [name, value] of [['License', me.license.id], ['Expires', new Date(me.license.expires_at).toLocaleString()], ['Device seats', String(me.license.seat_limit)]]) {
    appendText($('license-info'), 'dt', name);
    appendText($('license-info'), 'dd', value);
  }
  $('devices').replaceChildren();
  if (!devices.length) appendText($('devices'), 'p', 'No enrolled devices yet.');
  for (const device of devices) {
    const row = appendText($('devices'), 'div', '', 'device');
    appendText(row, 'strong', device.label);
    appendText(row, 'p', device.id);
    appendText(row, 'p', device.revoked ? 'Revoked' : `Last heartbeat: ${device.last_seen ? new Date(device.last_seen).toLocaleString() : 'Not received'}`);
    if (!device.revoked) {
      const button = appendText(row, 'button', 'Revoke this device', 'secondary');
      button.type = 'button';
      button.addEventListener('click', () => run(async () => {
        if (!window.confirm('Revoke this device credential and free its seat? This does not close broker positions.')) return;
        await api(`/v1/customer/devices/${encodeURIComponent(device.id)}/revoke`, 'POST');
        await refresh();
        message('Device credential revoked.');
      }));
    }
  }
  $('performance').replaceChildren();
  if (!performance.totals.length) appendText($('performance'), 'p', 'No demo summaries received. Your Windows bridge must submit them separately.');
  for (const item of performance.totals) {
    const row = appendText($('performance'), 'div', '', 'performance-row');
    appendText(row, 'strong', `${item.realized_pnl} ${item.currency} realized PnL`);
    appendText(row, 'p', `${item.closed_trades} closed trades · ${item.wins} wins · ${item.losses} losses`);
    appendText(row, 'p', `Largest reported daily drawdown: ${item.maximum_reported_daily_drawdown_pct}% · ${item.device_days} device-days`);
  }
  $('login-panel').hidden = true;
  $('workspace').hidden = false;
}

async function run(action) {
  if (busy) return;
  busy = true;
  document.querySelectorAll('button').forEach(button => { button.disabled = true; });
  try { await action(); }
  catch (error) { message(error instanceof Error ? error.message : 'Request failed.'); }
  finally {
    busy = false;
    document.querySelectorAll('button').forEach(button => { button.disabled = false; });
  }
}

$('login-form').addEventListener('submit', event => {
  event.preventDefault();
  run(async () => {
    licenseKey = $('license-key').value.trim();
    $('license-key').value = '';
    generation += 1;
    try { await refresh(); message('Workspace connected.'); }
    catch (error) { licenseKey = ''; throw error; }
  });
});
$('refresh').addEventListener('click', () => run(async () => { await refresh(); message('Workspace refreshed.'); }));
$('logout').addEventListener('click', signOut);
$('hide-key').addEventListener('click', hideCredential);
$('enroll-form').addEventListener('submit', event => {
  event.preventDefault();
  run(async () => {
    hideCredential();
    const result = await api('/v1/enroll', 'POST', { label: $('device-label').value.trim() });
    $('device-label').value = '';
    $('device-id').textContent = result.device_id;
    $('device-key').textContent = result.device_credential;
    $('new-credential').hidden = false;
    await refresh();
    message('Device enrolled. Save its one-time credential below.');
  });
});
// Clear the rendered tenant data as well as the key before a page is cached.
// Returning through the browser's Back button must require a fresh login.
window.addEventListener('pagehide', signOut);
