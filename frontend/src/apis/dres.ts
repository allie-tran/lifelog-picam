import { BACKEND_URL, DRES_URL } from 'constants/urls'
import axios from 'apis/defaultAxios'

export type Evaluation = {
    id: string
    name: string
}

export type Task = {
    id: string // evaluationId
    evaluationName: string

    name: string
    taskGroup: string
    taskType: string
    duration: number
}

export interface TaskRule {
    quickSubmit: boolean
    removeSubmitted: boolean
}

export interface SubmissionHistoryItem {
    notified?: boolean
    type: 'image' | 'text'
    content: string
    verdict: string
    timestamp?: Date
}

export type SubmitVerdict = 'CORRECT' | 'INCORRECT' | 'INVALID' | 'ERROR' | 'INDETERMINATE'

export interface SubmitResult {
    severity: 'success' | 'warning' | 'error' | 'info'
    message: string
    verdict: SubmitVerdict
}

const mapDresResponse = (data: any): SubmitResult => {
    const submission: string = data.submission ?? ''
    const description: string = data.description ?? ''
    const status: boolean = data.status ?? false

    if (!status || submission === 'INVALID') {
        return { severity: 'error', message: description, verdict: 'INVALID' }
    }
    if (submission === 'ERROR') {
        return { severity: 'error', message: description, verdict: 'ERROR' }
    }
    if (submission === 'CORRECT') {
        return { severity: 'success', message: description, verdict: 'CORRECT' }
    }
    if (submission === 'INCORRECT' || submission === 'WRONG') {
        return { severity: 'warning', message: description, verdict: 'INCORRECT' }
    }
    if (submission === 'INDETERMINATE') {
        return { severity: 'info', message: description, verdict: 'INDETERMINATE' }
    }
    return { severity: 'error', message: description || 'Unknown response', verdict: 'ERROR' }
}

export const sendLoginRequest = async (username: string, password: string) => {
    const url = `${DRES_URL}/login`
    return await axios.post(url, { username, password }, {
        headers: { 'Content-Type': 'application/json' },
    })
}

export const submitImage = async ({
    image,
    evaluationId,
    sessionId,
}: {
    image: string
    evaluationId: string
    sessionId: string
}): Promise<SubmitResult> => {
    const mediaItemName = image.split('/').pop()?.split('.')[0] + '_000' ?? image
    const url = `${DRES_URL}/submit/${evaluationId}?session=${sessionId}`
    const res = await axios.post(url, {
        answerSets: [{ answers: [{ mediaItemName }] }],
    })
    return mapDresResponse(res.data)
}

export const submitText = async ({
    text,
    evaluationId,
    sessionId,
}: {
    text: string
    evaluationId: string
    sessionId: string
}): Promise<SubmitResult> => {
    const url = `${DRES_URL}/submit/${evaluationId}?session=${sessionId}`
    const res = await axios.post(url, {
        answerSets: [{ answers: [{ text }] }],
    }, {
        headers: { 'Content-Type': 'application/json' },
    })
    return mapDresResponse(res.data)
}

export const getActiveEvaluations = async () => {
    const sessionId = localStorage.getItem('dresSessionId');
    const url = `${DRES_URL}/client/evaluation/list?session=${sessionId}`
    return axios.get(url)
}

export const getCurrentTask = async (evaluationId: string) => {
    const sessionId = localStorage.getItem('dresSessionId');
    const url = `${DRES_URL}/client/evaluation/currentTask/${evaluationId}?session=${sessionId}`
    return axios.get(url)
}
