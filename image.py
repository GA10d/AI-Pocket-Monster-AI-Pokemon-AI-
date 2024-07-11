import pygame

class Image(pygame.sprite.Sprite):
    def __init__(self, image_path, pos=(0,0), size = 0):
        self.path = image_path
        self.size = size
        self.image = pygame.image.load(self.path)
        self.image = pygame.transform.scale(self.image, self.size)
        self.pos = pos
    
    def draw(self, screen):
        screen.blit(self.image, self.getRect())
    
    def getRect(self):
        rect = self.image.get_rect()
        rect.x,rect.y = self.pos
        return rect
