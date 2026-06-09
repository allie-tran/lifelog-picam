import axios from 'axios';

export const DRES_BASE = 'https://vbs.videobrowsing.org/api/v2';

const dresAxios = axios.create({ baseURL: DRES_BASE });

export type SubmitVerdict = 'CORRECT' | 'INCORRECT' | 'INDETERMINATE' | 'INVALID' | 'ERROR';

export interface SubmitResult {
  verdict: SubmitVerdict;
  message: string;
}

function mapResponse(data: any): SubmitResult {
  const submission: string = data.submission ?? '';
  const description: string = data.description ?? '';
  const status: boolean = data.status ?? false;
  if (!status || submission === 'INVALID') { return { verdict: 'INVALID', message: description }; }
  if (submission === 'ERROR')               { return { verdict: 'ERROR',   message: description }; }
  if (submission === 'CORRECT')             { return { verdict: 'CORRECT', message: description }; }
  if (submission === 'INCORRECT' || submission === 'WRONG') {
    return { verdict: 'INCORRECT', message: description };
  }
  if (submission === 'INDETERMINATE')       { return { verdict: 'INDETERMINATE', message: description }; }
  return { verdict: 'ERROR', message: description || 'Unknown response' };
}

export const dresLoginApi = async (username: string, password: string): Promise<string> => {
  const res = await dresAxios.post('/login', { username, password });
  return res.data.sessionId ?? res.data.session ?? res.data.token;
};

export const getActiveEvaluations = async (
  sessionId: string,
): Promise<{ id: string; name: string }[]> => {
  const res = await dresAxios.get(`/client/evaluation/list?session=${sessionId}`);
  return res.data;
};

export const getCurrentTask = async (evaluationId: string, sessionId: string) => {
  const res = await dresAxios.get(
    `/client/evaluation/currentTask/${evaluationId}?session=${sessionId}`,
  );
  return res.data;
};

export const submitImageToDRES = async (
  imagePath: string,
  evaluationId: string,
  sessionId: string,
): Promise<SubmitResult> => {
  const stem = imagePath.split('/').pop()?.split('.')[0] ?? imagePath;
  const mediaItemName = `${stem}_000`;
  const res = await dresAxios.post(`/submit/${evaluationId}?session=${sessionId}`, {
    answerSets: [{ answers: [{ mediaItemName }] }],
  });
  return mapResponse(res.data);
};

export const submitTextToDRES = async (
  text: string,
  evaluationId: string,
  sessionId: string,
): Promise<SubmitResult> => {
  const res = await dresAxios.post(`/submit/${evaluationId}?session=${sessionId}`, {
    answerSets: [{ answers: [{ text }] }],
  });
  return mapResponse(res.data);
};
