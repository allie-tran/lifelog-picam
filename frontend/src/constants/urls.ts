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

export const DRES_URL = "https://vbs.videobrowsing.org/api/v2"

// Map tiles. Every map uses MAP_TILE_URL, so provider is chosen here once.
// Precedence:
//   1. REACT_APP_MAP_TILE_URL — explicit full URL override (any provider).
//   2. REACT_APP_STADIA_KEY   — Stadia Maps "Alidade Smooth" (~dataviz look),
//      the backup provider; needs a key + domain allowlisted at stadiamaps.com.
//   3. CARTO Positron         — free, no key, default fallback.
// {s} = subdomains, {r} = @2x retina suffix.
const _CARTO_URL = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
const _STADIA_KEY = process.env.REACT_APP_STADIA_KEY;
const _STADIA_URL = _STADIA_KEY
    ? `https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}{r}.png?api_key=${_STADIA_KEY}`
    : "";

export const MAP_TILE_URL =
    process.env.REACT_APP_MAP_TILE_URL || _STADIA_URL || _CARTO_URL;

const _OSM_ATTR =
    '<a href="https://www.openstreetmap.org/copyright" target="_blank">&copy; OpenStreetMap contributors</a>';
export const MAP_TILE_ATTRIBUTION = _STADIA_URL
    ? '<a href="https://stadiamaps.com/" target="_blank">&copy; Stadia Maps</a> ' +
      '<a href="https://openmaptiles.org/" target="_blank">&copy; OpenMapTiles</a> ' + _OSM_ATTR
    : _OSM_ATTR +
      ' <a href="https://carto.com/attributions" target="_blank">&copy; CARTO</a>';




