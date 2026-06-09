import React, { useEffect, useState } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import AsyncStorage from '@react-native-async-storage/async-storage';
import LoginScreen from '../screens/LoginScreen';
import RegisterScreen from '../screens/RegisterScreen';
import AdminScreen from '../screens/AdminScreen';
import UploadScreen from '../screens/UploadScreen';
import DeletedImagesScreen from '../screens/DeletedImagesScreen';
import DeleteRangeScreen from '../screens/DeleteRangeScreen';
import LocationMapScreen from '../screens/LocationMapScreen';
import MainTabs from './MainTabs';
import { useAppDispatch, useAppSelector } from '../store';
import { login } from '../store/slices/authSlice';
import { setHistory } from '../store/slices/searchSlice';
import { axiosInstance, COLORS, loadBackendUrl } from '../constants';
import { RootStackParamList } from '../types';

const Stack = createNativeStackNavigator<RootStackParamList>();

const RootNavigator = () => {
  const dispatch = useAppDispatch();
  const isAuthenticated = useAppSelector(s => s.auth.isAuthenticated);
  const [bootstrapping, setBootstrapping] = useState(true);

  useEffect(() => {
    const bootstrap = async () => {
      try {
        // Load server URL before any API calls
        await loadBackendUrl();

        // Restore search history
        const historyRaw = await AsyncStorage.getItem('searchHistory');
        if (historyRaw) {
          dispatch(setHistory(JSON.parse(historyRaw)));
        }

        // Verify auth token
        const token = await AsyncStorage.getItem('token');
        if (token) {
          axiosInstance.defaults.headers.common.Authorization = `Bearer ${token}`;
          const res = await axiosInstance.get('/auth/verify', { params: { token } });
          if (res.data.success) {
            const deviceIds = (res.data.devices ?? []).map((d: any) => d?.deviceId ?? d);
            dispatch(login({
              username: res.data.username,
              token,
              devices: deviceIds,
            }));
          }
        }
      } catch {}
      finally { setBootstrapping(false); }
    };
    bootstrap();
  }, []);

  if (bootstrapping) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: COLORS.background }}>
        <ActivityIndicator size="large" color={COLORS.primary} />
      </View>
    );
  }

  const headerDefaults = {
    headerShown: true,
    headerStyle: { backgroundColor: COLORS.surface },
    headerTintColor: COLORS.primary,
    headerTitleStyle: { fontWeight: '700' as const },
  };

  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      {isAuthenticated ? (
        <>
          <Stack.Screen name="Main" component={MainTabs} />
          <Stack.Screen name="Admin" component={AdminScreen}
            options={{ ...headerDefaults, headerTintColor: COLORS.purple, title: 'Admin Panel' }} />
          <Stack.Screen name="Upload" component={UploadScreen}
            options={{ ...headerDefaults, title: 'Upload Images' }} />
          <Stack.Screen name="DeletedImages" component={DeletedImagesScreen}
            options={{ ...headerDefaults, title: 'Deleted Images' }} />
          <Stack.Screen name="DeleteRange" component={DeleteRangeScreen}
            options={{ ...headerDefaults, title: 'Delete by Date' }} />
          <Stack.Screen name="LocationMap" component={LocationMapScreen}
            options={{ ...headerDefaults, title: 'Location Map' }} />
        </>
      ) : (
        <>
          <Stack.Screen name="Login" component={LoginScreen} />
          <Stack.Screen name="Register" component={RegisterScreen} />
        </>
      )}
    </Stack.Navigator>
  );
};

export default RootNavigator;
