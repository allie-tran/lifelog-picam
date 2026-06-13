export const minutesToHM = (m: number): string => {
    const total = Math.round(m);
    const h = Math.floor(total / 60);
    const mm = total % 60;
    if (h === 0) return `${mm} min`;
    if (mm === 0) return `${h} h`;
    return `${h} h ${mm} min`;
};
