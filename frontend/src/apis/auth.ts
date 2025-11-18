
import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';
import { AccessLevel, UserInfo } from 'types/auth';

export const createUserRequest = (username: string, password: string, email: string, adminCode: string) => {
    return axios.post(`${BACKEND_URL}/auth/register`, {
        username,
        password,
        email,
        adminCode
    });
}

export const loginRequest = (username: string, password: string) => {
    return axios.post(`${BACKEND_URL}/auth/login`, {
        username,
        password
    });
}

export const verifyTokenRequest = (token: string) => {
    return axios.get(`${BACKEND_URL}/auth/verify?token=${token}`);
}

export const getUsers = async (token: string) => {
    const response = await axios.get(`${BACKEND_URL}/auth/users`, {
        headers: {
            'Authorization': `Bearer ${token}`
        }
    });
    return response.data as UserInfo[];
}

export const changeUserAccess = async (token: string, username: string, deviceId: string, accessLevel: AccessLevel) => {
    const response = await axios.post(`${BACKEND_URL}/auth/change-access`, {
        username,
        deviceId,
        accessLevel
    }, {
        headers: {
            'Authorization': `Bearer ${token}`
        }
    });
    return response.data;
}


