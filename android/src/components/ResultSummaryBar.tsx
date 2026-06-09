import React, { useEffect, useMemo, useState } from 'react';
import {
  Image,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import dayjs from 'dayjs';
import { COLORS } from '../constants';
import { useAppDispatch, useAppSelector } from '../store';
import { setSearchQuery } from '../store/slices/searchSlice';
import { getAllFaces } from '../api/browsing';
import { CountItem, ImageObject, LocationSummaryItem } from '../types';

interface Props {
  results: ImageObject[][];
  topLocations: LocationSummaryItem[];
  topCountries: CountItem[];
  topPeople: CountItem[];
  onAppendToQuery: (text: string) => void;
}

const Row = ({ icon, children }: { icon: string; children: React.ReactNode }) => (
  <View style={styles.row}>
    <Text style={styles.rowIcon}>{icon}</Text>
    <View style={styles.rowContent}>{children}</View>
  </View>
);

const Chip = ({
  label,
  onPress,
  accent,
}: {
  label: string;
  onPress: () => void;
  accent?: boolean;
}) => (
  <TouchableOpacity
    style={[styles.chip, accent && styles.chipAccent]}
    onPress={onPress}
    activeOpacity={0.7}
  >
    <Text style={[styles.chipText, accent && styles.chipTextAccent]}>{label}</Text>
  </TouchableOpacity>
);

const ResultSummaryBar = ({
  results,
  topLocations,
  topCountries,
  topPeople,
  onAppendToQuery,
}: Props) => {
  const dispatch = useAppDispatch();
  const deviceId = useAppSelector(s => s.auth.deviceId);
  const { locationIds, peopleIds } = useAppSelector(s => s.search.query);

  const [faces, setFaces] = useState<{ id: string; name: string; images: string[] }[]>([]);

  useEffect(() => {
    if (!deviceId || topPeople.length === 0) { return; }
    getAllFaces(deviceId)
      .then(res => setFaces(res.data))
      .catch(() => {});
  }, [deviceId, topPeople.length]);

  const faceByName = useMemo(() => {
    const map: Record<string, { id: string; image: string }> = {};
    for (const f of faces) {
      map[f.name] = { id: f.id, image: f.images[0] ?? '' };
    }
    return map;
  }, [faces]);

  const { dateRange, eventCount, photoCount } = useMemo(() => {
    const flat = results.flat();
    const dates = flat
      .map(img => img.date ?? img.timestamp?.slice(0, 10))
      .filter(Boolean)
      .sort() as string[];
    let range = '';
    if (dates.length) {
      const first = dayjs(dates[0]);
      const last = dayjs(dates[dates.length - 1]);
      if (first.isSame(last, 'day')) {
        range = first.format('D MMM YYYY');
      } else if (first.isSame(last, 'year')) {
        range = `${first.format('D MMM')} – ${last.format('D MMM YYYY')}`;
      } else {
        range = `${first.format('D MMM YYYY')} – ${last.format('D MMM YYYY')}`;
      }
    }
    return { dateRange: range, eventCount: results.length, photoCount: flat.length };
  }, [results]);

  const addLocation = (loc: LocationSummaryItem) => {
    onAppendToQuery(loc.name);
    if (loc.id && !locationIds.includes(loc.id)) {
      dispatch(setSearchQuery({ locationIds: [...locationIds, loc.id] }));
    }
  };

  const addPerson = (name: string) => {
    onAppendToQuery(name);
    const face = faceByName[name];
    if (face && !peopleIds.includes(face.id)) {
      dispatch(setSearchQuery({ peopleIds: [...peopleIds, face.id] }));
    }
  };

  return (
    <View style={styles.card}>
      {/* Stats */}
      <Row icon="📅">
        <Text style={styles.statText}>{dateRange}</Text>
      </Row>
      <Row icon="📋">
        <Text style={styles.statText}>
          <Text style={styles.statNum}>{eventCount}</Text> events ·{' '}
          <Text style={styles.statNum}>{photoCount}</Text> photos
        </Text>
      </Row>

      {/* Locations */}
      {topLocations.length > 0 && (
        <Row icon="📍">
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
            {topLocations.map(loc => (
              <Chip
                key={loc.id ?? loc.name}
                label={`${loc.name} (${loc.count})`}
                onPress={() => addLocation(loc)}
                accent={!!loc.id && locationIds.includes(loc.id)}
              />
            ))}
          </ScrollView>
        </Row>
      )}

      {/* Countries */}
      {topCountries.length > 0 && (
        <Row icon="🌍">
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
            {topCountries.map(c => (
              <Chip
                key={c.name}
                label={`${c.name} (${c.count})`}
                onPress={() => onAppendToQuery(c.name)}
              />
            ))}
          </ScrollView>
        </Row>
      )}

      {/* People */}
      {topPeople.length > 0 && (
        <Row icon="👤">
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.people}>
            {topPeople.map(person => {
              const face = faceByName[person.name];
              const isActive = face ? peopleIds.includes(face.id) : false;
              return (
                <TouchableOpacity
                  key={person.name}
                  style={styles.personItem}
                  onPress={() => addPerson(person.name)}
                  activeOpacity={0.75}
                >
                  {face?.image ? (
                    <Image
                      source={{ uri: face.image }}
                      style={[styles.avatar, isActive && styles.avatarActive]}
                      resizeMode="cover"
                    />
                  ) : (
                    <View style={[styles.avatar, styles.avatarPlaceholder, isActive && styles.avatarActive]}>
                      <Text style={styles.avatarInitial}>
                        {person.name.charAt(0).toUpperCase()}
                      </Text>
                    </View>
                  )}
                  <Text style={styles.personName} numberOfLines={1}>
                    {person.name}
                  </Text>
                  <Text style={styles.personCount}>{person.count}</Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        </Row>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  card: {
    backgroundColor: COLORS.surface,
    marginHorizontal: 8,
    marginBottom: 8,
    borderRadius: 14,
    paddingVertical: 10,
    paddingHorizontal: 12,
    elevation: 2,
    gap: 6,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  rowIcon: { fontSize: 13, width: 18, textAlign: 'center' },
  rowContent: { flex: 1 },
  statText: { fontSize: 13, color: COLORS.textSecondary },
  statNum: { fontWeight: '700', color: COLORS.textPrimary },
  chips: { gap: 5, paddingVertical: 2 },
  chip: {
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderRadius: 12,
    backgroundColor: COLORS.background,
    borderWidth: 1,
    borderColor: COLORS.divider,
  },
  chipAccent: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  chipText: { fontSize: 11, color: COLORS.textSecondary },
  chipTextAccent: { color: '#fff', fontWeight: '600' },
  people: { gap: 10, paddingVertical: 2 },
  personItem: { alignItems: 'center', width: 52 },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    borderWidth: 2,
    borderColor: COLORS.divider,
  },
  avatarActive: { borderColor: COLORS.secondary, borderWidth: 2.5 },
  avatarPlaceholder: {
    backgroundColor: COLORS.divider,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarInitial: { fontSize: 16, fontWeight: '700', color: COLORS.textSecondary },
  personName: {
    marginTop: 3,
    fontSize: 9,
    color: COLORS.textPrimary,
    textAlign: 'center',
    maxWidth: 50,
  },
  personCount: { fontSize: 8, color: COLORS.textSecondary },
});

export default ResultSummaryBar;
