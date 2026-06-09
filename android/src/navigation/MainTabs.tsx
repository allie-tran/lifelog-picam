import React from 'react';
import { Text, View } from 'react-native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import BrowseScreen from '../screens/BrowseScreen';
import SearchScreen from '../screens/SearchScreen';
import FacesScreen from '../screens/FacesScreen';
import DRESScreen from '../screens/DRESScreen';
import GPSScreen from '../screens/GPSScreen';
import BiometricsScreen from '../screens/BiometricsScreen';
import NotificationsScreen from '../screens/NotificationsScreen';
import SettingsScreen from '../screens/SettingsScreen';
import { COLORS } from '../constants';
import { useAppSelector } from '../store';

const Tab = createBottomTabNavigator();

const icon = (emoji: string, focused: boolean) => (
  <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.55 }}>{emoji}</Text>
);

const BellIcon = ({ focused }: { focused: boolean }) => {
  const unreadCount = useAppSelector(s => s.notifications.unreadCount);
  return (
    <View>
      <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.55 }}>🔔</Text>
      {unreadCount > 0 && (
        <View style={{
          position: 'absolute', top: -4, right: -6,
          backgroundColor: COLORS.primary, borderRadius: 7,
          minWidth: 14, height: 14, alignItems: 'center', justifyContent: 'center',
        }}>
          <Text style={{ fontSize: 9, color: '#fff', fontWeight: '700' }}>
            {unreadCount > 99 ? '99+' : String(unreadCount)}
          </Text>
        </View>
      )}
    </View>
  );
};

const MainTabs = () => (
  <Tab.Navigator
    screenOptions={{
      headerShown: true,
      tabBarActiveTintColor: COLORS.primary,
      tabBarInactiveTintColor: COLORS.textSecondary,
      tabBarStyle: {
        backgroundColor: COLORS.surface,
        borderTopColor: COLORS.divider,
        elevation: 4,
      },
      headerStyle: { backgroundColor: COLORS.surface },
      headerTintColor: COLORS.textPrimary,
      headerTitleStyle: { fontWeight: '700' },
    }}
  >
    <Tab.Screen
      name="Browse"
      component={BrowseScreen}
      options={{
        title: 'Browse',
        tabBarIcon: ({ focused }) => icon('🏠', focused),
      }}
    />
    <Tab.Screen
      name="Search"
      component={SearchScreen}
      options={{
        title: 'Search',
        tabBarIcon: ({ focused }) => icon('🔍', focused),
      }}
    />
    <Tab.Screen
      name="People"
      component={FacesScreen}
      options={{
        title: 'People',
        tabBarIcon: ({ focused }) => icon('👤', focused),
      }}
    />
    <Tab.Screen
      name="GPS"
      component={GPSScreen}
      options={{
        title: 'GPS',
        tabBarIcon: ({ focused }) => icon('📍', focused),
      }}
    />
    <Tab.Screen
      name="Biometrics"
      component={BiometricsScreen}
      options={{
        title: 'Bio',
        tabBarIcon: ({ focused }) => icon('📊', focused),
      }}
    />
    <Tab.Screen
      name="DRES"
      component={DRESScreen}
      options={{
        title: 'DRES',
        tabBarIcon: ({ focused }) => icon('🏆', focused),
      }}
    />
    <Tab.Screen
      name="Notifications"
      component={NotificationsScreen}
      options={{
        title: 'Alerts',
        tabBarIcon: ({ focused }) => <BellIcon focused={focused} />,
        headerShown: false,
      }}
    />
    <Tab.Screen
      name="Settings"
      component={SettingsScreen}
      options={{
        title: 'Settings',
        tabBarIcon: ({ focused }) => icon('⚙️', focused),
      }}
    />
  </Tab.Navigator>
);

export default MainTabs;
