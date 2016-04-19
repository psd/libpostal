
import copy
import os
import six
import yaml

from collections import Mapping

from geodata.address_expansions.address_dictionaries import address_phrase_dictionaries
from geodata.math.sampling import cdf, check_probability_distribution


this_dir = os.path.realpath(os.path.dirname(__file__))

ADDRESS_CONFIG_DIR = os.path.join(this_dir, os.pardir, os.pardir, os.pardir,
                                  'resources', 'addresses')

DICTIONARIES_DIR = os.path.join(this_dir, os.pardir, os.pardir, os.pardir,
                                'resources', 'dictionaries')


def recursive_merge(a, b):
    for k, v in six.iteritems(b):
        if isinstance(v, Mapping):
            existing = a.get(k, v)
            merged = recursive_merge(existing, v)
            a[k] = merged
        else:
            a[k] = b[k]
    return a


class DoesNotExist:
    pass


def nested_get(obj, keys):
    if len(keys) == 0:
        return obj
    try:
        for key in keys[:-1]:
            obj = obj.get(key, {})
            if not hasattr(obj, 'items'):
                return DoesNotExist
        key = keys[-1]
        return obj.get(key, DoesNotExist)
    except AttributeError:
        return DoesNotExist


class AddressConfig(object):
    def __init__(self, config_dir=ADDRESS_CONFIG_DIR, dictionaries_dir=DICTIONARIES_DIR):
        self.address_configs = {}
        self.cache = {}

        for filename in os.listdir(config_dir):
            if filename not in ('en.yaml', 'es.yaml'):
                continue

            config = yaml.load(open(os.path.join(ADDRESS_CONFIG_DIR, filename)))
            countries = config.pop('countries', {})

            for k in countries.keys():
                country_config = countries[k]
                config_copy = copy.deepcopy(config)
                countries[k] = recursive_merge(config_copy, country_config)

            config['countries'] = countries

            lang = filename.strip('.yaml')
            self.address_configs[lang] = config

        self.sample_phrases = {}

        for language in address_phrase_dictionaries.languages:
            for dictionary in address_phrase_dictionaries.language_dictionaries[language]:
                self.sample_phrases[(language, dictionary)] = {}
                for phrases in address_phrase_dictionaries.phrases[(language, dictionary)]:
                    self.sample_phrases[(language, dictionary)][phrases[0]] = phrases[1:]

    def get_property(self, key, language, country=None, default=None):
        keys = key.split('.')
        config = self.address_configs.get(language, {})

        if country:
            country_config = config.get('countries', {}).get(country, {})
            if country_config:
                config = country_config

        value = nested_get(config, keys)
        if value is not DoesNotExist:
            return value

        return default

    def cache_key(self, prop, language, dictionaries=(), country=None):
        return (prop, language, country, tuple(dictionaries))

    def alternative_probabilities(self, prop, language, dictionaries=(), country=None):
        '''Get a probability distribution over alternatives'''
        key = self.cache_key(prop, language, dictionaries, country=country)
        if key not in self.cache:
            properties = self.get_property(prop, language, country=country, default=None)

            if properties is None:
                return None, None

            probs = []
            alternatives = []

            if 'probability' in properties:
                prob = properties['probability']
                props = properties['default']
                phrases, phrase_probs = self.form_probabilities(props, language, dictionaries=dictionaries)
                probs.extend([prob * p for p in phrase_probs])
                alternatives.extend([(p, props) for p in phrases])
            elif 'alternatives' not in properties:
                prob = 1.0
                props = properties['default']
                phrases, phrase_probs = self.form_probabilities(props, language, dictionaries=dictionaries)
                probs.extend([prob * p for p in phrase_probs])
                alternatives.extend([(p, props) for p in phrases])

            sample_probability = properties.get('sample_probability')
            if sample_probability is not None:
                sample_phrases = []
                for dictionary in dictionaries:
                    phrases = self.sample_phrases.get((language, dictionary), [])
                    for canonical, surface_forms in six.iteritems(phrases):
                        sample_phrases.append(canonical)
                        sample_phrases.extend(surface_forms)
                # Note: use the outer properties dictionary e.g. units.alphanumeric
                alternatives.extend([(p, properties) for p in sample_phrases])
                probs.extend([float(sample_probability) / len(sample_phrases)] * len(sample_phrases))

            alts = properties.get('alternatives', [])
            for alt in alts:
                prob = alt.get('probability', 1.0 / len(alts))
                props = alt['alternative']
                phrases, phrase_probs = self.form_probabilities(props, language, dictionaries=dictionaries)
                probs.extend([prob * p for p in phrase_probs])
                alternatives.extend([(p, props) for p in phrases])

            try:
                check_probability_distribution(probs)
            except AssertionError:
                print 'values were: {}'.format(alternatives)
                raise

            probs_cdf = cdf(probs)
            self.cache[key] = (alternatives, probs_cdf)
        return self.cache[key]

    def form_probabilities(self, properties, language, dictionaries=()):
        probs = []
        alternatives = []
        canonical_prob = properties.get('canonical_probability', 1.0)
        canonical = properties['canonical']

        alternatives.append(canonical)
        probs.append(canonical_prob)

        if 'abbreviated_probability' in properties:
            probs.append(properties['abbreviated_probability'])
            abbreviated = properties['abbreviated']
            assert isinstance(abbreviated, basestring)
            alternatives.append(abbreviated)

        if properties.get('sample', False) and 'sample_probability' in properties:
            sample_prob = properties['sample_probability']
            samples = set()
            for dictionary in dictionaries:
                phrases = self.sample_phrases.get((language, dictionary), {})
                samples |= set(phrases.get(canonical, []))
            if 'sample_exclude' in properties:
                samples -= set(properties['sample_exclude'])
            if samples:
                for phrase in samples:
                    probs.append(sample_prob / float(len(samples)))
                    alternatives.append(phrase)
            else:
                total = sum(probs)
                probs = [p / total for p in probs]

        try:
            check_probability_distribution(probs)
        except AssertionError:
            print 'values were: {}'.format(alternatives)
            raise

        return alternatives, probs

address_config = AddressConfig()