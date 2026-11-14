"""A user uploads, replaces and removes their own profile picture."""
import io
import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from ops.models import User
from ops.tests.helpers import GOOD_PASSWORD

MEDIA = tempfile.mkdtemp(prefix="campusdesk-test-media-")


def picture(name="me.png", fmt="PNG", size=(40, 40)):
    """A real image file, made in memory, the way a browser would send it."""
    data = io.BytesIO()
    Image.new("RGB", size, "navy").save(data, fmt)
    return SimpleUploadedFile(name, data.getvalue(), content_type="image/" + fmt.lower())


@override_settings(MEDIA_ROOT=MEDIA)
class ProfilePictureTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = User.objects.create_user(username="rae@x.com", email="rae@x.com", password=GOOD_PASSWORD,
                                             first_name="Rae", last_name="Port")
        self.client.login(username="rae@x.com", password=GOOD_PASSWORD)

    def upload(self, file):
        data = {"action": "avatar"}
        if file is not None:
            data["avatar"] = file
        return self.client.post("/profile/", data, follow=True)

    def stored(self):
        self.user.refresh_from_db()
        return self.user.avatar.name

    def on_disk(self, name):
        return os.path.exists(os.path.join(MEDIA, name))

    # ---- uploading

    def test_a_picture_is_saved_under_avatars_and_shown_on_the_profile(self):
        resp = self.upload(picture())
        name = self.stored()
        self.assertTrue(name.startswith(f"avatars/user-{self.user.pk}-"))
        self.assertTrue(self.on_disk(name))
        self.assertContains(resp, "Profile picture updated")
        self.assertContains(resp, f'src="/media/{name}"')

    def test_without_a_picture_the_profile_shows_the_default_icon(self):
        html = self.client.get("/profile/").content.decode()
        self.assertIn("images/profile_icon.jpeg", html)
        self.assertNotIn("Remove picture", html)

    def test_jpeg_png_and_webp_are_accepted(self):
        for name, fmt, extension in (("a.jpg", "JPEG", ".jpg"), ("a.png", "PNG", ".png"), ("a.webp", "WEBP", ".webp")):
            self.upload(picture(name, fmt))
            self.assertTrue(self.stored().endswith(extension), fmt)

    def test_the_saved_name_never_uses_what_the_uploader_called_the_file(self):
        self.upload(picture("../../evil name<script>.png"))
        name = self.stored()
        self.assertNotIn("evil", name)
        self.assertNotIn("..", name)
        self.assertTrue(self.on_disk(name))

    def test_the_extension_comes_from_the_image_not_from_the_file_name(self):
        """A PNG sent as photo.jpg is stored as a .png."""
        self.upload(picture("photo.jpg", "PNG"))
        self.assertTrue(self.stored().endswith(".png"))

    # ---- refusing

    def test_a_file_that_is_not_an_image_is_refused_whatever_it_is_called(self):
        fake = SimpleUploadedFile("me.png", b"<?php echo 'not a picture'; ?>", content_type="image/png")
        resp = self.upload(fake)
        self.assertEqual(self.stored(), "")
        self.assertContains(resp, "Upload a valid image")

    def test_a_gif_and_an_svg_are_refused(self):
        resp = self.upload(picture("me.gif", "GIF"))
        self.assertContains(resp, "Upload a JPEG, PNG or WebP picture")
        svg = SimpleUploadedFile("me.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
                                 content_type="image/svg+xml")
        self.upload(svg)
        self.assertEqual(self.stored(), "")

    def test_a_picture_larger_than_2_mb_is_refused(self):
        big = SimpleUploadedFile("big.png", picture().read() + b"\0" * (2 * 1024 * 1024), content_type="image/png")
        resp = self.upload(big)
        self.assertContains(resp, "larger than 2 MB")
        self.assertEqual(self.stored(), "")

    def test_sending_no_file_says_to_choose_one(self):
        self.assertContains(self.upload(None), "Choose a picture to upload")

    # ---- replacing and removing

    def test_a_new_picture_replaces_the_old_file(self):
        self.upload(picture())
        first = self.stored()
        self.upload(picture())
        second = self.stored()
        self.assertNotEqual(first, second)
        self.assertFalse(self.on_disk(first))
        self.assertTrue(self.on_disk(second))

    def test_a_refused_upload_keeps_the_picture_the_user_already_has(self):
        self.upload(picture())
        kept = self.stored()
        self.upload(SimpleUploadedFile("x.png", b"nope", content_type="image/png"))
        self.assertEqual(self.stored(), kept)
        self.assertTrue(self.on_disk(kept))

    def test_removing_deletes_the_file_and_brings_back_the_default_icon(self):
        self.upload(picture())
        name = self.stored()
        resp = self.client.post("/profile/", {"action": "remove_avatar"}, follow=True)
        self.assertEqual(self.stored(), "")
        self.assertFalse(self.on_disk(name))
        self.assertContains(resp, "Profile picture removed")
        self.assertContains(resp, "images/profile_icon.jpeg")

    # ---- the rest of the profile form still works

    def test_saving_the_bio_does_not_touch_the_picture(self):
        self.upload(picture())
        name = self.stored()
        self.client.post("/profile/", {"bio": "I fix printers"})
        self.user.refresh_from_db()
        self.assertEqual((self.user.bio, self.user.avatar.name), ("I fix printers", name))

    def test_a_user_only_ever_changes_their_own_picture(self):
        other = User.objects.create_user(username="tim@x.com", email="tim@x.com", password=GOOD_PASSWORD)
        self.upload(picture())
        other.refresh_from_db()
        self.assertEqual(other.avatar.name, "")

    def test_a_visitor_who_is_not_signed_in_cannot_upload(self):
        self.client.logout()
        resp = self.client.post("/profile/", {"action": "avatar", "avatar": picture()})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp.url)
