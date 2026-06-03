export enum AccessLevel {
    OWNER = 'owner',
    VIEWER = 'viewer',
    ADMIN = 'admin',
    NONE = 'none'
}

export type DeviceAccess = {
    deviceId: string;
    accessLevel: AccessLevel;
};

export type SensorDevice = {
    deviceId: string;
    deviceNickname: string;
    sensorType: string;
}

export type UserInfo = {
    username: string;
    devices: DeviceAccess[];
    sensors: SensorDevice[];
};
