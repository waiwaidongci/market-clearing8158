import {feedback, field} from '../components/common/fields.js';
import {empty, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {handler} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, link, p} from '../utils/dom.js';

const KIND_PILL = {'跨日待定':'cross', '缺校时依据':'missing'};

function calibrationForm(refresh, message) {
  const submit = button('登记校时记录', {type:'submit', class:'primary', 'data-testid':'save-calibration'});
  const fields = [
    {key:'device_id', label:'收银设备编号', type:'string', required:true, max_length:80},
    {key:'device_time', label:'设备时间（带时区）', type:'string', required:true, max_length:40,
      help:'ISO-8601 格式，如 2026-11-20T23:50:00+08:00'},
    {key:'standard_time', label:'标准时间（带时区）', type:'string', required:true, max_length:40,
      help:'联网校时读到的真实时间，同样带时区偏移'},
  ];
  return el('form', {class:'fields', onSubmit:handler(submit, message, async event => {
    const data = Object.fromEntries(new FormData(event.target).entries());
    const saved = await workspace.registerCalibration(data);
    message.textContent = saved.created
      ? `已登记设备 ${saved.device_id} 的校时，偏差 ${saved.offset_seconds} 秒，请选择批次重算。`
      : '该设备时间已有相同校时记录，已按幂等忽略重复提交。';
    event.target.reset();
    await refresh();
  })}, ...fields.map(item => field(item)), submit, message);
}

export async function clockPage(route, refresh) {
  const {spec, datasets} = workspace;
  const [calibrations, pending] = await Promise.all([
    workspace.calibrations(), workspace.pending(route.id || undefined),
  ]);
  const message = feedback();
  const selectedId = route.id || datasets[0]?.id;

  const calibrationTable = table([
    {key:'device_id', label:'设备编号'},
    {key:'device_time', label:'设备时间'},
    {key:'standard_time', label:'标准时间'},
    {label:'偏差（秒）', render:row => pill(String(row.offset_seconds), row.offset_seconds >= 0 ? 'cross' : 'missing')},
    {key:'author', label:'登记人'},
  ], calibrations, {caption:'校时记录', empty:'还没有校时记录，请先登记。'});

  const pendingTable = table([
    {key:'transaction_key', label:'流水号'},
    {key:'device_id', label:'设备编号'},
    {key:'recorded_day', label:'设备记账日'},
    {label:'待定原因', render:row => pill(row.reason_kind, KIND_PILL[row.reason_kind] || 'missing')},
    {key:'pending_reason', label:'原因说明'},
    {key:'range_start', label:'真实时间起'},
    {key:'range_end', label:'真实时间止'},
    {key:'basis', label:'归属依据'},
  ], pending, {caption:'挂起台账（待定原因与归属依据）', empty:'当前没有挂起流水，所有食堂核销均已归属。', pageSize:8});

  const recomputeButton = button('按最新校时重算营业日', {class:'primary', 'data-testid':'recompute'});
  recomputeButton.addEventListener('click', handler(recomputeButton, message, async () => {
    const result = await workspace.recompute(selectedId);
    const days = result.affected_days.length ? result.affected_days.join('、') : '无';
    message.textContent = `重算完成：受影响营业日 ${days}；挂起 ${result.pending_count} 笔、已归属 ${result.attributed_count} 笔。跨日改归属的两个营业日已一并重算，重复提交不会重复计账。`;
    await refresh();
  }));
  const recompute = session.canWrite && selectedId && el('div', {class:'actions'},
    recomputeButton, link('前往日终清分', '#run', {class:'quiet'}));

  const picker = datasets.length && el('label', {for:'clock-dataset', class:'field'}, el('span',{}, '选择数据批次'),
    el('select', {id:'clock-dataset', onChange:event => { location.hash = `#clock/${event.target.value}`; }},
      datasets.map(item => el('option', {value:item.id, selected:item.id === selectedId},
        `${item.name} · ${item.row_count} 行`))));

  return el('div', {class:'two-col'},
    el('div', {class:'wide-panel'},
      panel('校时记录', p('收银机离线时钟会漂移，用前后两次校时（标准时间减设备时间）夹出每笔核销的真实时间区间。允许乱序补录，补录后只重算受影响营业日。', 'subtle'),
        picker, calibrationTable, recompute, message),
      panel('挂起台账', p('只有真实时间区间整体落在同一北京时间自然日才归入该营业日清分；跨日或缺校时依据的先挂起，可在此回查待定原因与归属依据。', 'subtle'),
        pendingTable)),
    el('aside', {class:'sidebar-panel'},
      panel('登记校时', session.canWrite
        ? calibrationForm(refresh, feedback())
        : p('只读角色可查看校时记录与挂起台账。', 'empty')),
      panel('判定口径', el('ul', {class:'method-list'}, [
        '偏差 = 标准时间 − 设备时间，取前后两次校时偏差的最小/最大值夹出真实时间闭区间。',
        '区间整体在同一自然日 → 归入该营业日双账清分。',
        '区间跨日 → 挂起（跨日待定）；缺前置或后置校时 → 挂起（缺校时依据）。',
        '校园卡账沿用卡中心原日期，不参与设备时钟校正。',
      ].map(text => el('li', {}, text))))));
}
