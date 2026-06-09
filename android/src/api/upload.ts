import { axiosInstance } from '../constants';

export const initUpload = (device: string, dateFormat: string) =>
  axiosInstance.post<{ uploadId: string }>('/ingest/init', { device, dateFormat });

export const uploadChunk = (
  uploadId: string,
  chunkIndex: number,
  totalChunks: number,
  chunkUri: string,
) => {
  const form = new FormData();
  form.append('upload_id', uploadId);
  form.append('chunk_index', String(chunkIndex));
  form.append('total_chunks', String(totalChunks));
  form.append('chunk', {
    uri: chunkUri,
    type: 'application/octet-stream',
    name: 'chunk.bin',
  } as any);
  return axiosInstance.post('/ingest/chunk', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

export const completeUpload = (uploadId: string) =>
  axiosInstance.post<{ jobId: string }>('/ingest/complete', { uploadId });

export const getProcessingStatus = (jobId: string) =>
  axiosInstance.get<{ jobId: string; status: string; progress: number; message?: string }>(
    `/ingest/processing-status/${jobId}`,
  );
