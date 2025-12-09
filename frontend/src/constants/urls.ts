import { getCookie, parseErrorResponse } from "utils/misc";
import axios from "axios";

export const BASE_URL = `${window.location.origin}/${window.location.pathname.split("/")[1]}`;
let BACKEND_URL = `${BASE_URL}/be`;
let IMAGE_HOST_URL = `${window.location.origin}/images/LifelogPicam/`;

if (window.location.hostname === "localhost") {
  BACKEND_URL = `http://localhost:8082`;
  IMAGE_HOST_URL = `http://localhost:9000/LifelogPicam/`;
}


const api = axios.create({
    baseURL: BACKEND_URL,
    timeout: 60000,
});

api.interceptors.request.use(
    function (config) {
        const token = getCookie('token');
        if (token) {
            config.headers['Authorization'] = `Bearer ${token}`;
        }
        return config;
    },
    function (error: any) {
        console.error('There was an error setting auth header!', error);
        alert(parseErrorResponse(error.response));
        return Promise.reject(error)
    }
)

export const THUMBNAIL_HOST_URL = IMAGE_HOST_URL;
export { BACKEND_URL, IMAGE_HOST_URL, api };

