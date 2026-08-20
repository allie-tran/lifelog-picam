export enum AccessLevel {
    OWNER = 'owner',
    VIEWER = 'viewer',
    ADMIN = 'admin',
    NONE = 'none'
}

// Which UI tier the frontend renders. 'simple' hides power-user clutter
// (DRES, chat, upload, admin, resync); 'advanced' is the full UI.
export enum UIMode {
    SIMPLE = 'simple',
    ADVANCED = 'advanced'
}

export type DeviceAccess = {
    deviceId: string;
    accessLevel: AccessLevel;
};

export type SensorDevice = {
    associatedUser: string;
    deviceId: string;
    deviceNickname: string;
    sensorType: string;
    secret: string;
}

export type UserInfo = {
    username: string;
    devices: DeviceAccess[];
    sensors: SensorDevice[];
};
