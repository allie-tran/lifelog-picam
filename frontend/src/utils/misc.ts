export const parseErrorResponse = (response: any) => {
    if (!response) {
        return 'Unknown error occurred';
    }
    let errorMessage = `HTTP error! status: ${response.status}`;
    console.log(response);
    if (response.data?.detail) {
        errorMessage = response.data.detail;
    } else if (response.statusText) {
        errorMessage = response.statusText;
    }
    return errorMessage;
};

export function getCookie(cname: string) {
    let name = cname + '=';
    let decodedCookie = decodeURIComponent(document.cookie);
    let ca = decodedCookie.split(';');
    for (let i = 0; i < ca.length; i++) {
        let c = ca[i];
        while (c.charAt(0) == ' ') {
            c = c.substring(1);
        }
        if (c.indexOf(name) == 0) {
            console.log('Found cookie:', c.substring(name.length, c.length));
            return c.substring(name.length, c.length);
        }
    }
    return '';
}
