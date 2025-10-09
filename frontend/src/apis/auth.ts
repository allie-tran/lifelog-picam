
import axios from 'axios';
import { BACKEND_URL } from '../constants/urls';

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
