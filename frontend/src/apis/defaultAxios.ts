import axios from 'axios';
import { getCookie, parseErrorResponse } from 'utils/misc';
import { BACKEND_URL } from '../constants/urls';

axios.defaults.headers.common['Authorization'] = `Bearer ${getCookie('token')}`;
axios.defaults.baseURL = BACKEND_URL;
axios.interceptors.request.use(
    function (config) {
        const token = getCookie('token');
        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`;
            config.headers['Custom-Axios'] = 'true';
        }
        return config;
    },
    function (error: any) {
        console.error('There was an error setting auth header!', error);
        alert(parseErrorResponse(error.response));
        return Promise.reject(error);
    }
);

export default axios;
