import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { COLORS } from '../constants';
import {
  DeviceAccess,
  SensorDevice,
  UserInfo,
  addSensorToUser,
  changeUserAccess,
  getUsers,
} from '../api/admin';

const ACCESS_LEVELS = ['owner', 'viewer', 'admin', 'none'];
const ACCESS_COLORS: Record<string, string> = {
  owner: '#155724', admin: '#856404', viewer: '#004085', none: '#383d41',
};
const ACCESS_BG: Record<string, string> = {
  owner: '#d4edda', admin: '#fff3cd', viewer: '#cce5ff', none: '#e2e3e5',
};

const AdminScreen = () => {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  // Device access modal
  const [deviceModal, setDeviceModal] = useState(false);
  const [daUsername, setDaUsername] = useState('');
  const [daDeviceId, setDaDeviceId] = useState('');
  const [daLevel, setDaLevel] = useState('viewer');
  const [saving, setSaving] = useState(false);

  // Sensor modal
  const [sensorModal, setSensorModal] = useState(false);
  const [saUsername, setSaUsername] = useState('');
  const [saDeviceId, setSaDeviceId] = useState('');
  const [saType, setSaType] = useState('biometrics');
  const [saSecret, setSaSecret] = useState('');
  const [saNickname, setSaNickname] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await getUsers();
      setUsers(res.data);
      setError('');
    } catch {
      setError('Not authorised to view admin panel.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openDeviceModal = (username: string, device?: DeviceAccess) => {
    setDaUsername(username);
    setDaDeviceId(device?.deviceId ?? '');
    setDaLevel(device?.accessLevel ?? 'viewer');
    setDeviceModal(true);
  };

  const openSensorModal = (username: string, sensor?: SensorDevice) => {
    setSaUsername(username);
    setSaDeviceId(sensor?.deviceId ?? '');
    setSaType(sensor?.sensorType ?? 'biometrics');
    setSaSecret(sensor?.secret ?? '');
    setSaNickname(sensor?.deviceNickname ?? '');
    setSensorModal(true);
  };

  const handleSaveDeviceAccess = async () => {
    if (!daUsername || !daDeviceId) {
      Alert.alert('Required', 'Username and Device ID are required.');
      return;
    }
    setSaving(true);
    try {
      await changeUserAccess(daUsername, daDeviceId, daLevel);
      setDeviceModal(false);
      load();
    } catch {
      Alert.alert('Error', 'Failed to update device access.');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveSensorAccess = async () => {
    if (!saUsername || !saDeviceId || !saNickname) {
      Alert.alert('Required', 'Username, Device ID and Nickname are required.');
      return;
    }
    setSaving(true);
    try {
      await addSensorToUser(saDeviceId, saType, saSecret, saNickname, saUsername);
      setSensorModal(false);
      load();
    } catch {
      Alert.alert('Error', 'Failed to update sensor access.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={COLORS.primary} />
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.errorText}>{error}</Text>
      </View>
    );
  }

  return (
    <>
      <ScrollView style={styles.container} contentContainerStyle={styles.content}>
        <View style={styles.header}>
          <Text style={styles.title}>Admin Panel</Text>
          <TouchableOpacity
            onPress={() => { setRefreshing(true); load(); }}
            disabled={refreshing}
          >
            <Text style={styles.refreshText}>{refreshing ? '…' : '↻ Refresh'}</Text>
          </TouchableOpacity>
        </View>

        {users.map(user => (
          <View key={user.username} style={styles.userCard}>
            {/* User header */}
            <View style={styles.userHeader}>
              <Text style={styles.username}>👤 {user.username}</Text>
              <View style={styles.userBtns}>
                <TouchableOpacity
                  style={styles.addBtn}
                  onPress={() => openDeviceModal(user.username)}
                >
                  <Text style={styles.addBtnText}>+ Device</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.addBtn, { backgroundColor: COLORS.secondary }]}
                  onPress={() => openSensorModal(user.username)}
                >
                  <Text style={styles.addBtnText}>+ Sensor</Text>
                </TouchableOpacity>
              </View>
            </View>

            {/* Camera devices */}
            <Text style={styles.subLabel}>Camera Access</Text>
            {user.devices && user.devices.length > 0 ? (
              user.devices.map(d => (
                <TouchableOpacity
                  key={d.deviceId}
                  style={styles.deviceRow}
                  onPress={() => openDeviceModal(user.username, d)}
                >
                  <Text style={styles.deviceId} numberOfLines={1}>📷 {d.deviceId}</Text>
                  <View style={[styles.levelBadge, { backgroundColor: ACCESS_BG[d.accessLevel] ?? ACCESS_BG.none }]}>
                    <Text style={[styles.levelText, { color: ACCESS_COLORS[d.accessLevel] ?? ACCESS_COLORS.none }]}>
                      {d.accessLevel.toUpperCase()}
                    </Text>
                  </View>
                </TouchableOpacity>
              ))
            ) : (
              <Text style={styles.emptyHint}>No device access</Text>
            )}

            {/* Sensor devices */}
            <Text style={[styles.subLabel, { marginTop: 10 }]}>Sensor Devices</Text>
            {user.sensors && user.sensors.length > 0 ? (
              user.sensors.map(s => (
                <TouchableOpacity
                  key={s.deviceNickname}
                  style={styles.deviceRow}
                  onPress={() => openSensorModal(user.username, s)}
                >
                  <Text style={styles.deviceId} numberOfLines={1}>❤ {s.deviceNickname}</Text>
                  <View style={[styles.levelBadge, { backgroundColor: '#e8d5f5' }]}>
                    <Text style={[styles.levelText, { color: COLORS.purple }]}>
                      {s.sensorType.toUpperCase()}
                    </Text>
                  </View>
                </TouchableOpacity>
              ))
            ) : (
              <Text style={styles.emptyHint}>No sensor devices</Text>
            )}
          </View>
        ))}
      </ScrollView>

      {/* Device access modal */}
      <Modal visible={deviceModal} transparent animationType="slide" onRequestClose={() => setDeviceModal(false)}>
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Device Access</Text>
            <Text style={styles.fieldLabel}>User</Text>
            <View style={styles.readonlyField}>
              <Text style={styles.readonlyText}>{daUsername}</Text>
            </View>
            <Text style={styles.fieldLabel}>Device ID</Text>
            <TextInput
              style={styles.input}
              value={daDeviceId}
              onChangeText={setDaDeviceId}
              placeholder="e.g. picam_001"
              placeholderTextColor={COLORS.textSecondary}
              autoCapitalize="none"
            />
            <Text style={styles.fieldLabel}>Access Level</Text>
            <View style={styles.levelPicker}>
              {ACCESS_LEVELS.map(l => (
                <TouchableOpacity
                  key={l}
                  style={[styles.levelOption, daLevel === l && styles.levelOptionActive]}
                  onPress={() => setDaLevel(l)}
                >
                  <Text style={[styles.levelOptionText, daLevel === l && styles.levelOptionTextActive]}>
                    {l.toUpperCase()}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
            <View style={styles.modalBtns}>
              <TouchableOpacity style={styles.cancelBtn} onPress={() => setDeviceModal(false)}>
                <Text style={styles.cancelBtnText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.saveBtn, saving && styles.saveBtnDisabled]}
                onPress={handleSaveDeviceAccess}
                disabled={saving}
              >
                {saving ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.saveBtnText}>Save</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>

      {/* Sensor access modal */}
      <Modal visible={sensorModal} transparent animationType="slide" onRequestClose={() => setSensorModal(false)}>
        <View style={styles.modalOverlay}>
          <ScrollView>
            <View style={styles.modalCard}>
              <Text style={styles.modalTitle}>Sensor Device</Text>
              <Text style={styles.fieldLabel}>User</Text>
              <View style={styles.readonlyField}>
                <Text style={styles.readonlyText}>{saUsername}</Text>
              </View>
              <Text style={styles.fieldLabel}>Device ID</Text>
              <TextInput style={styles.input} value={saDeviceId} onChangeText={setSaDeviceId}
                placeholder="Device identifier" placeholderTextColor={COLORS.textSecondary} autoCapitalize="none" />
              <Text style={styles.fieldLabel}>Nickname</Text>
              <TextInput style={styles.input} value={saNickname} onChangeText={setSaNickname}
                placeholder="e.g. Polar H10" placeholderTextColor={COLORS.textSecondary} />
              <Text style={styles.fieldLabel}>Sensor Type</Text>
              <TextInput style={styles.input} value={saType} onChangeText={setSaType}
                placeholder="e.g. biometrics" placeholderTextColor={COLORS.textSecondary} autoCapitalize="none" />
              <Text style={styles.fieldLabel}>Secret (camera only, blank for biometrics)</Text>
              <TextInput style={styles.input} value={saSecret} onChangeText={setSaSecret}
                placeholder="Leave blank for biometrics" placeholderTextColor={COLORS.textSecondary} autoCapitalize="none" />
              <View style={styles.modalBtns}>
                <TouchableOpacity style={styles.cancelBtn} onPress={() => setSensorModal(false)}>
                  <Text style={styles.cancelBtnText}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.saveBtn, saving && styles.saveBtnDisabled]}
                  onPress={handleSaveSensorAccess}
                  disabled={saving}
                >
                  {saving ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.saveBtnText}>Save</Text>}
                </TouchableOpacity>
              </View>
            </View>
          </ScrollView>
        </View>
      </Modal>
    </>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  content: { padding: 14, paddingBottom: 40 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  errorText: { fontSize: 14, color: COLORS.error, textAlign: 'center' },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 },
  title: { fontSize: 20, fontWeight: '700', color: COLORS.purple },
  refreshText: { fontSize: 13, color: COLORS.secondary, fontWeight: '600' },
  userCard: {
    backgroundColor: COLORS.surface, borderRadius: 14, padding: 14,
    marginBottom: 12, elevation: 2,
  },
  userHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 },
  username: { fontSize: 15, fontWeight: '700', color: COLORS.textPrimary, flex: 1 },
  userBtns: { flexDirection: 'row', gap: 6 },
  addBtn: {
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8,
    backgroundColor: COLORS.primary,
  },
  addBtnText: { color: '#fff', fontSize: 11, fontWeight: '700' },
  subLabel: { fontSize: 10, fontWeight: '700', color: COLORS.textSecondary, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 },
  deviceRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingVertical: 8, paddingHorizontal: 10, borderRadius: 8,
    borderWidth: 1, borderColor: COLORS.divider, marginBottom: 4,
  },
  deviceId: { fontSize: 12, color: COLORS.textPrimary, flex: 1, marginRight: 8 },
  levelBadge: { paddingHorizontal: 8, paddingVertical: 2, borderRadius: 6 },
  levelText: { fontSize: 10, fontWeight: '700', letterSpacing: 0.4 },
  emptyHint: { fontSize: 12, color: COLORS.textSecondary, fontStyle: 'italic', paddingLeft: 4, paddingBottom: 4 },
  // Modal
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modalCard: {
    backgroundColor: COLORS.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: 20, paddingBottom: 34, gap: 8,
  },
  modalTitle: { fontSize: 16, fontWeight: '700', color: COLORS.textPrimary, marginBottom: 4, textAlign: 'center' },
  fieldLabel: { fontSize: 11, fontWeight: '600', color: COLORS.textSecondary, textTransform: 'uppercase', letterSpacing: 0.4 },
  readonlyField: {
    borderWidth: 1, borderColor: COLORS.divider, borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 9, backgroundColor: COLORS.background,
  },
  readonlyText: { fontSize: 14, color: COLORS.textSecondary },
  input: {
    borderWidth: 1, borderColor: COLORS.divider, borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 9, fontSize: 14, color: COLORS.textPrimary,
  },
  levelPicker: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  levelOption: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8,
    borderWidth: 1, borderColor: COLORS.divider,
  },
  levelOptionActive: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  levelOptionText: { fontSize: 12, color: COLORS.textSecondary },
  levelOptionTextActive: { color: '#fff', fontWeight: '700' },
  modalBtns: { flexDirection: 'row', gap: 10, marginTop: 6 },
  cancelBtn: {
    flex: 1, paddingVertical: 12, borderRadius: 10,
    borderWidth: 1, borderColor: COLORS.divider, alignItems: 'center',
  },
  cancelBtnText: { fontSize: 14, color: COLORS.textSecondary, fontWeight: '600' },
  saveBtn: { flex: 1, paddingVertical: 12, borderRadius: 10, backgroundColor: COLORS.secondary, alignItems: 'center' },
  saveBtnDisabled: { opacity: 0.5 },
  saveBtnText: { color: '#fff', fontWeight: '700', fontSize: 14 },
});

export default AdminScreen;
