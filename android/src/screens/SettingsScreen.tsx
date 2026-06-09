import React, { useState } from 'react';
import {
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { useAppDispatch, useAppSelector } from '../store';
import { logout, setDeviceId } from '../store/slices/authSlice';
import { clearHistory } from '../store/slices/searchSlice';
import { config, COLORS, setBackendUrl } from '../constants';
import type { RootStackParamList } from '../types';

const SettingsScreen = () => {
  const dispatch = useAppDispatch();
  const navigation = useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const { deviceId, devices, username } = useAppSelector(s => s.auth);
  const historyCount = useAppSelector(s => s.search.history.length);
  const [urlInput, setUrlInput] = useState(config.backendUrl);

  const handleSaveUrl = async () => {
    const trimmed = urlInput.trim();
    if (!trimmed) { return; }
    await setBackendUrl(trimmed);
    Alert.alert('Server URL updated', `Now connecting to:\n${trimmed}`);
  };

  const handleLogout = async () => {
    Alert.alert('Logout', 'Are you sure?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Logout', style: 'destructive', onPress: async () => {
          await AsyncStorage.removeItem('token');
          await AsyncStorage.removeItem('dresSessionId');
          dispatch(logout());
        },
      },
    ]);
  };

  const handleClearHistory = () => {
    Alert.alert('Clear Search History', 'Remove all saved searches?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Clear', style: 'destructive', onPress: () => dispatch(clearHistory()) },
    ]);
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>Settings</Text>

      {/* Server */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Server</Text>
        <Text style={styles.hint}>Backend URL (e.g. http://192.168.1.10:8082)</Text>
        <TextInput
          style={styles.urlInput}
          value={urlInput}
          onChangeText={setUrlInput}
          placeholder="http://10.0.2.2:8082"
          placeholderTextColor={COLORS.textSecondary}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          returnKeyType="done"
          onSubmitEditing={handleSaveUrl}
        />
        <TouchableOpacity
          style={[styles.saveUrlBtn, !urlInput.trim() && styles.saveUrlBtnDisabled]}
          onPress={handleSaveUrl}
          disabled={!urlInput.trim()}
        >
          <Text style={styles.saveUrlBtnText}>Save URL</Text>
        </TouchableOpacity>
      </View>

      {/* Account */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Account</Text>
        <View style={styles.row}>
          <Text style={styles.rowLabel}>Username</Text>
          <Text style={styles.rowValue}>{username}</Text>
        </View>
        <TouchableOpacity style={styles.dangerRow} onPress={handleLogout}>
          <Text style={styles.dangerText}>Logout</Text>
        </TouchableOpacity>
      </View>

      {/* Device */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Device</Text>
        <Text style={styles.hint}>Select the camera device to browse and search</Text>
        {devices.map(d => (
          <TouchableOpacity
            key={d}
            style={[styles.deviceRow, deviceId === d && styles.deviceRowActive]}
            onPress={() => dispatch(setDeviceId(d))}
          >
            <Text style={[styles.deviceText, deviceId === d && styles.deviceTextActive]}>
              {d}
            </Text>
            {deviceId === d && <Text style={styles.checkmark}>✓</Text>}
          </TouchableOpacity>
        ))}
      </View>

      {/* Search */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Search</Text>
        <View style={styles.row}>
          <Text style={styles.rowLabel}>Saved searches</Text>
          <Text style={styles.rowValue}>{historyCount}</Text>
        </View>
        <TouchableOpacity style={styles.dangerRow} onPress={handleClearHistory}>
          <Text style={styles.dangerText}>Clear search history</Text>
        </TouchableOpacity>
      </View>

      {/* Images */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Images</Text>
        <TouchableOpacity style={styles.navRow} onPress={() => navigation.navigate('Upload')}>
          <Text style={styles.navRowLabel}>Upload ZIP</Text>
          <Text style={styles.navRowArrow}>›</Text>
        </TouchableOpacity>
        <View style={styles.divider} />
        <TouchableOpacity style={styles.navRow} onPress={() => navigation.navigate('DeletedImages')}>
          <Text style={styles.navRowLabel}>Deleted Images</Text>
          <Text style={styles.navRowArrow}>›</Text>
        </TouchableOpacity>
        <View style={styles.divider} />
        <TouchableOpacity style={styles.navRow} onPress={() => navigation.navigate('DeleteRange')}>
          <Text style={styles.navRowLabel}>Delete by Date</Text>
          <Text style={styles.navRowArrow}>›</Text>
        </TouchableOpacity>
      </View>

      {/* Admin */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Administration</Text>
        <TouchableOpacity style={styles.navRow} onPress={() => navigation.navigate('Admin')}>
          <Text style={styles.navRowLabel}>Admin Panel</Text>
          <Text style={styles.navRowArrow}>›</Text>
        </TouchableOpacity>
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  content: { padding: 16, paddingBottom: 40 },
  title: { fontSize: 22, fontWeight: '700', color: COLORS.purple, marginBottom: 20 },
  section: {
    backgroundColor: COLORS.surface, borderRadius: 14, padding: 16,
    marginBottom: 14, elevation: 1,
  },
  sectionTitle: { fontSize: 12, fontWeight: '700', color: COLORS.textSecondary, marginBottom: 12, textTransform: 'uppercase', letterSpacing: 0.5 },
  hint: { fontSize: 12, color: COLORS.textSecondary, marginBottom: 8 },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderColor: COLORS.divider },
  rowLabel: { fontSize: 14, color: COLORS.textPrimary },
  rowValue: { fontSize: 14, color: COLORS.textSecondary },
  dangerRow: { paddingVertical: 10, marginTop: 4 },
  dangerText: { fontSize: 14, color: COLORS.primary, fontWeight: '600' },
  navRow: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingVertical: 10,
  },
  navRowLabel: { fontSize: 14, color: COLORS.textPrimary, fontWeight: '600' },
  navRowArrow: { fontSize: 20, color: COLORS.textSecondary },
  divider: { height: 1, backgroundColor: COLORS.divider },
  urlInput: {
    borderWidth: 1, borderColor: COLORS.divider, borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 9, fontSize: 13,
    color: COLORS.textPrimary, marginBottom: 8, fontFamily: 'monospace',
  },
  saveUrlBtn: {
    backgroundColor: COLORS.secondary, borderRadius: 10,
    paddingVertical: 10, alignItems: 'center',
  },
  saveUrlBtnDisabled: { opacity: 0.4 },
  saveUrlBtnText: { color: '#fff', fontWeight: '700', fontSize: 13 },
  deviceRow: {
    paddingVertical: 10, paddingHorizontal: 12, borderRadius: 8,
    borderWidth: 1, borderColor: COLORS.divider, marginBottom: 6,
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
  },
  deviceRowActive: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  deviceText: { fontSize: 13, color: COLORS.textPrimary },
  deviceTextActive: { color: '#fff', fontWeight: '600' },
  checkmark: { color: '#fff', fontWeight: '700' },
});

export default SettingsScreen;
