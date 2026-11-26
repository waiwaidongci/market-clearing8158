import {request, saveFile} from '../api/http.js';
import {session} from './session.js';

const call = (path, body) => request(path, {token:session.token, body});
export const workspace = {
  spec: null,
  datasets: [],
  runs: [],
  async init() { this.spec = await request('/spec'); },
  async refresh() { [this.datasets, this.runs] = await Promise.all([call('/datasets'), call('/runs')]); },
  getDataset: (id, offset = 0) => call(`/datasets/${id}?offset=${offset}`),
  getRun: id => call(`/runs/${id}`),
  upload: data => call('/datasets', data),
  start: data => call('/runs', data),
  review: (id, data) => call(`/runs/${id}/review`, data),
  audit: () => call('/audit'),
  schedules: () => call('/schedules'),
  deliveries: () => call('/deliveries'),
  schedule: data => call('/schedules', data),
  disable: id => call(`/schedules/${id}/disable`, {}),
  calibrations: () => call('/clock/calibrations'),
  pending: (datasetId, day) => call(`/clock/pending?${new URLSearchParams(
    Object.entries({dataset_id:datasetId, day}).filter(([,v]) => v !== undefined && v !== null && v !== ''))}`),
  registerCalibration: data => call('/clock/calibrations', data),
  recompute: datasetId => call('/clock/recompute', {dataset_id:datasetId}),
  download: (path, filename) => saveFile(path, session.token, filename),
};
