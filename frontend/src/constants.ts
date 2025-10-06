export const BASE_URL = `${window.location.origin}/${window.location.pathname.split("/")[1]}`;
let BACKEND_URL = `${BASE_URL}/be`;
let IMAGE_HOST_URL = `${window.location.origin}/images/LifelogPicam/`;

if (window.location.hostname === "localhost") {
  BACKEND_URL = `http://localhost:8082`;
  IMAGE_HOST_URL = `http://localhost:9000/LifelogPicam/`;
}

export const THUMBNAIL_HOST_URL = `${IMAGE_HOST_URL}thumbnails/`;

export { BACKEND_URL, IMAGE_HOST_URL };

