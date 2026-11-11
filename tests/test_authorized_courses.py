"""Locally stored authorized-course list: validation and persistence only."""
import json
import tempfile
import unittest
from pathlib import Path

from campus_ai.authorized_courses import (AuthorizedCourse, DEFAULT_COURSES, MAX_COURSES, load, save)


class AuthorizedCourseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'authorized_courses.json'

    def test_default_is_only_the_course_the_student_authorized(self):
        courses = load(self.path)
        self.assertEqual([(c.course_id, c.name) for c in courses], [('7653', 'Modelagem UML')])
        self.assertEqual(courses[0].url, 'https://ead.aedb.br/ava/course/view.php?id=7653')
        self.assertFalse(self.path.exists(), 'loading must not write')

    def test_url_is_built_only_from_a_numeric_id(self):
        for bad in ('', '0', '07', '12a', '1&id=2', '../x', 7653, None, '1' * 11):
            with self.subTest(course_id=bad), self.assertRaises(ValueError):
                AuthorizedCourse(bad, 'Nome')

    def test_name_is_normalized_and_bounded(self):
        self.assertEqual(AuthorizedCourse('5', '  Modelagem \n UML ').name, 'Modelagem UML')
        for bad in ('', '   ', 'x' * 201):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                AuthorizedCourse('5', bad)

    def test_round_trip(self):
        original = [AuthorizedCourse('7653', 'Modelagem UML'), AuthorizedCourse('12', 'Outra fictícia')]
        save(original, self.path)
        self.assertEqual(load(self.path), original)
        self.assertNotIn('cookie', self.path.read_text(encoding='utf-8').lower())

    def test_corrupt_or_invalid_entries_never_widen_the_authorization(self):
        self.path.write_text('{not json', encoding='utf-8')
        self.assertEqual(load(self.path), list(DEFAULT_COURSES))
        self.path.write_text(json.dumps({'courses': [
            {'id': '9', 'name': 'Válida fictícia'}, {'id': 'x', 'name': 'Inválida'},
            {'id': '10'}, 'texto', {'id': '9', 'name': 'Duplicada'}]}), encoding='utf-8')
        self.assertEqual([c.course_id for c in load(self.path)], ['9'])

    def test_list_is_capped(self):
        courses = [AuthorizedCourse(str(i + 1), f'Disciplina {i}') for i in range(MAX_COURSES + 1)]
        with self.assertRaises(ValueError):
            save(courses, self.path)
        self.assertFalse(self.path.exists())

    def test_explicitly_empty_list_stays_empty(self):
        save([], self.path)
        self.assertEqual(load(self.path), [])


if __name__ == '__main__':
    unittest.main()
