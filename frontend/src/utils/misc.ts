export const parseErrorResponse = (response: any) => {
    let errorMessage = `HTTP error! status: ${response.status}`;
    console.log(response);
    if (response.data?.detail) {
        errorMessage = response.data.detail;
    } else if (response.statusText) {
        errorMessage = response.statusText;
    }
    return errorMessage;
}


