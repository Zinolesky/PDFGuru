export const TEXT_FIELD_OPTIONS = [
  // Personal
  { key: 'first_name', label: 'First name', group: 'Personal' },
  { key: 'last_name', label: 'Last name', group: 'Personal' },
  { key: 'middle_name', label: 'Middle name', group: 'Personal' },
  { key: 'full_name', label: 'Full name', group: 'Personal' },
  { key: 'title', label: 'Title', group: 'Personal' },
  { key: 'date_of_birth', label: 'Date of birth', group: 'Personal' },
  { key: 'nationality', label: 'Nationality', group: 'Personal' },
  { key: 'id_number', label: 'ID / Passport number', group: 'Personal' },

  // Contact & Address
  { key: 'email', label: 'Email address', group: 'Contact' },
  { key: 'phone_number', label: 'Phone number', group: 'Contact' },
  { key: 'alt_phone_number', label: 'Alternative phone number', group: 'Contact' },
  { key: 'residential_address', label: 'Residential address', group: 'Contact' },
  { key: 'mailing_address', label: 'Mailing address', group: 'Contact' },
  { key: 'city', label: 'City', group: 'Contact' },
  { key: 'state', label: 'State / Province', group: 'Contact' },
  { key: 'postal_code', label: 'Postal / ZIP code', group: 'Contact' },
  { key: 'country', label: 'Country', group: 'Contact' },

  // Organization & Work
  { key: 'occupation', label: 'Occupation / Job title', group: 'Organization' },
  { key: 'employer_name', label: 'Employer / Organization', group: 'Organization' },
  { key: 'department', label: 'Department', group: 'Organization' },
  { key: 'start_date', label: 'Start date', group: 'Organization' },

  // Emergency & Financial
  { key: 'emergency_contact_name', label: 'Emergency contact name', group: 'Emergency & Financial' },
  { key: 'emergency_contact_relationship', label: 'Emergency contact relationship', group: 'Emergency & Financial' },
  { key: 'emergency_contact_phone', label: 'Emergency contact phone', group: 'Emergency & Financial' },
  { key: 'bank_name', label: 'Bank name', group: 'Emergency & Financial' },
  { key: 'bank_account_name', label: 'Account holder name', group: 'Emergency & Financial' },
  { key: 'bank_account_number', label: 'Account number', group: 'Emergency & Financial' },
  { key: 'amount', label: 'Amount', group: 'Emergency & Financial' },

  // General
  { key: 'notes', label: 'Notes / Comments', group: 'General' },
  { key: 'date_signed', label: 'Date', group: 'General' },
];

export const CHECKBOX_FIELD_OPTIONS = {
  gender: {
    label: 'Gender',
    values: ['Male', 'Female', 'Other'],
  },
  marital_status: {
    label: 'Marital status',
    values: ['Single', 'Married', 'Divorced', 'Widowed'],
  },
  preferred_contact: {
    label: 'Preferred contact',
    values: ['Email', 'Phone', 'SMS'],
  },
  employment_status: {
    label: 'Employment status',
    values: ['Full-Time', 'Part-Time', 'Self-Employed', 'Contractor', 'Student'],
  },
  yes_no: {
    label: 'Yes / No Question',
    values: ['Yes', 'No'],
  },
};

export const IMAGE_FIELD_OPTIONS = [
  { key: 'profile_photo', label: 'Profile / ID Photo', defaultMode: 'photo' },
  { key: 'applicant_signature', label: 'Applicant Signature', defaultMode: 'signature' },
  { key: 'witness_signature', label: 'Witness Signature', defaultMode: 'signature' },
  { key: 'company_stamp', label: 'Official Stamp / Seal', defaultMode: 'signature' },
];

export const FIELD_LABELS = {
  first_name: 'First name',
  last_name: 'Last name',
  middle_name: 'Middle name',
  surname: 'Surname / Last name',
  other_names: 'Other names',
  full_name: 'Full name',
  title: 'Title',
  date_of_birth: 'Date of birth',
  nationality: 'Nationality',
  citizenship: 'Citizenship',
  id_number: 'ID / Passport number',
  email: 'Email address',
  phone_number: 'Phone number',
  alt_phone_number: 'Alternative phone number',
  residential_address: 'Residential address',
  mailing_address: 'Mailing address',
  city: 'City',
  state: 'State / Province',
  postal_code: 'Postal / ZIP code',
  country: 'Country',
  gender: 'Gender',
  marital_status: 'Marital status',
  preferred_contact: 'Preferred contact',
  occupation: 'Occupation / Job title',
  employer_name: 'Employer / Organization',
  department: 'Department',
  start_date: 'Start date',
  emergency_contact_name: 'Emergency contact name',
  emergency_contact_relationship: 'Emergency contact relationship',
  emergency_contact_phone: 'Emergency contact phone',
  bank_name: 'Bank name',
  bank_account_name: 'Account holder name',
  bank_account_number: 'Account number',
  amount: 'Amount',
  notes: 'Notes / Comments',
  additional_notes_or_special_requests: 'Additional notes or special requests',
  additional_comments: 'Additional comments',
  date_signed: 'Date',
  profile_photo: 'Profile / ID photo',
  passport_photo: 'Profile / ID photo',
  applicant_signature: 'Signature',
  client_signature: 'Signature',
  witness_signature: 'Witness signature',
  company_stamp: 'Official stamp / Seal',
};

export const SAMPLE_DEMO_VALUES = {
  first_name: 'Jordan',
  last_name: 'Rivera',
  surname: 'Rivera',
  other_names: 'Jordan',
  full_name: 'Jordan Rivera',
  title: 'Ms',
  date_of_birth: '14/06/1993',
  nationality: 'Canadian',
  email: 'jordan.rivera@example.com',
  phone_number: '+1 (555) 234-8910',
  residential_address: '420 Cedar Grove Avenue, Suite 12',
  mailing_address: '420 Cedar Grove Avenue, Suite 12',
  city: 'Toronto',
  state: 'Ontario',
  postal_code: 'M5V 2T6',
  country: 'Canada',
  gender: 'Female',
  marital_status: 'Single',
  preferred_contact: 'Email',
  occupation: 'Product Designer',
  employer_name: 'Northstar Studio Inc.',
  department: 'Design Systems',
  start_date: '01/12/2026',
  emergency_contact_name: 'Alex Rivera',
  emergency_contact_relationship: 'Sibling',
  emergency_contact_phone: '+1 (555) 987-6543',
  amount: '$2,500.00',
  notes: 'Confirmed availability for remote onboarding and digital document verification.',
  additional_notes_or_special_requests: 'Confirmed availability for digital onboarding and welcome kit delivery.',
  additional_comments: 'All equipment preferences confirmed.',
  date_signed: '21/11/2026',
};

export function isSignatureLikeKey(fieldKey = '') {
  const k = String(fieldKey).toLowerCase();
  return k.includes('sign') || k.includes('initial') || k.includes('stamp') || k.includes('seal');
}

export function checkboxMatchesValue(fieldVal, matchVal) {
  if (fieldVal === null || fieldVal === undefined || !matchVal) return false;
  const vStr = String(fieldVal).trim().toLowerCase();
  const mStr = String(matchVal).trim().toLowerCase();
  if (!vStr) return false;
  if (vStr === mStr) return true;
  const vCompact = vStr.replace(/[\s\-_]+/g, '');
  const mCompact = mStr.replace(/[\s\-_]+/g, '');
  if (vCompact === mCompact) return true;
  if (mCompact === 'yes' && ['true', '1', 'y', 'checked'].includes(vCompact)) return true;
  return false;
}

export function humanizeFieldKey(key, explicitLabel = null) {
  if (explicitLabel && explicitLabel.trim()) return explicitLabel.trim();
  if (FIELD_LABELS[key]) return FIELD_LABELS[key];
  const cleaned = String(key || 'field')
    .replace(/[_-]+/g, ' ')
    .trim();
  if (!cleaned) return 'Field';
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

export function slugifyLabel(label) {
  return (
    String(label || '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 48) || 'custom_field'
  );
}

export function buildDocumentDictionarySpec(template) {
  if (!template || !template.mappings) {
    return {
      fields: [],
      nonImageFields: [],
      imageFields: [],
      blankDictionaryText: '',
      guidedDictionaryText: '',
    };
  }

  const splitKeyRedirect = {
    dob_dd: 'date_of_birth',
    dob_mm: 'date_of_birth',
    dob_yyyy: 'date_of_birth',
    date_dd: 'date_signed',
    date_mm: 'date_signed',
    date_yyyy: 'date_signed',
  };

  const sortedMappings = [...template.mappings].sort((a, b) => {
    const pa = a.page_number || 1;
    const pb = b.page_number || 1;
    if (pa !== pb) return pa - pb;
    const yEffA =
      a.type === 'checkbox'
        ? a.y_pct || 0
        : (a.y_pct || 0) + Math.min(0.012, Math.max(0, a.height_pct || 0) * 0.45);
    const yEffB =
      b.type === 'checkbox'
        ? b.y_pct || 0
        : (b.y_pct || 0) + Math.min(0.012, Math.max(0, b.height_pct || 0) * 0.45);
    const bandA = Math.round(yEffA / 0.015);
    const bandB = Math.round(yEffB / 0.015);
    if (bandA !== bandB) return bandA - bandB;
    const fA = (a.question_text || '').includes(' — ') || (a.label || '').includes(' — ') ? 1 : 0;
    const fB = (b.question_text || '').includes(' — ') || (b.label || '').includes(' — ') ? 1 : 0;
    if (fA !== fB) return fA - fB;
    return (a.x_pct || 0) - (b.x_pct || 0);
  });

  const fieldMap = new Map();

  sortedMappings.forEach((m) => {
    const rawKey = m.field_key || 'field';
    const fKey = splitKeyRedirect[rawKey] || rawKey;
    const mType = splitKeyRedirect[rawKey] ? 'text' : m.type || 'text';
    const fLabel = splitKeyRedirect[rawKey]
      ? humanizeFieldKey(fKey)
      : humanizeFieldKey(fKey, m.label);
    const pageNum = m.page_number || 1;

    if (!fieldMap.has(fKey)) {
      fieldMap.set(fKey, {
        field_key: fKey,
        label: fLabel,
        question_text: m.question_text || null,
        section: m.section || null,
        type: mType,
        options: [],
        page_numbers: [pageNum],
        confidence: m.confidence ?? null,
        detection_source: m.detection_source || null,
      });
    } else {
      const existing = fieldMap.get(fKey);
      if (!existing.page_numbers.includes(pageNum)) {
        existing.page_numbers.push(pageNum);
      }
      if (mType === 'checkbox') {
        existing.type = 'checkbox';
      } else if (mType === 'multiline' && existing.type === 'text') {
        existing.type = 'multiline';
      }
      if (m.confidence != null && (existing.confidence == null || m.confidence < existing.confidence)) {
        existing.confidence = m.confidence;
      }
      if (
        m.question_text &&
        (!existing.question_text || m.question_text.length > existing.question_text.length)
      ) {
        existing.question_text = m.question_text;
      }
      if (!existing.section && m.section) {
        existing.section = m.section;
      }
    }

    if (mType === 'checkbox' && m.match_value) {
      const entry = fieldMap.get(fKey);
      if (!entry.options.includes(m.match_value)) {
        entry.options.push(m.match_value);
      }
    }
  });

  const allFields = Array.from(fieldMap.values());
  const nonImageFields = allFields.filter((f) => f.type !== 'image');
  const imageFields = allFields.filter((f) => f.type === 'image');

  const blankLines = nonImageFields.map((f) => `${f.label}: `);
  const guidedLines = nonImageFields.map((f) =>
    f.type === 'checkbox' && f.options.length > 0
      ? `${f.label} (${f.options.join(' / ')}): `
      : `${f.label}: `
  );

  return {
    fields: [...nonImageFields, ...imageFields],
    nonImageFields,
    imageFields,
    blankDictionaryText: blankLines.join('\n'),
    guidedDictionaryText: guidedLines.join('\n'),
  };
}
